"""
Background watcher that auto-unblocks stuck cluster deletions.

Behaviour:
  - Polls OpenStackCluster every 30 s (up to 15 min total)
  - RouterInterfaceInUseByFloatingIP  → releases blocking FIPs via OpenStack SDK
  - Any other stuck condition > 5 min  → strips finalizers (force-remove)
"""

import asyncio, base64, logging, os, re, tempfile
from kubernetes import client as k8s_client
from kubernetes.client.exceptions import ApiException

log = logging.getLogger(__name__)

CAPO_GROUP   = "infrastructure.cluster.x-k8s.io"
CAPO_VERSION = "v1beta1"
CAPI_GROUP   = "cluster.x-k8s.io"
CAPI_VERSION = "v1beta2"

_custom = k8s_client.CustomObjectsApi()
_core   = k8s_client.CoreV1Api()

_POLL_INTERVAL = 30       # s between polls
_FORCE_AFTER   = 5 * 60   # strip finalizers after 5 min stuck on same error
_MAX_WAIT      = 15 * 60  # give up after 15 min


async def watch_and_force_delete(namespace: str, name: str) -> None:
    """Call as a BackgroundTask right after initiating cluster deletion."""
    log.info("[force-delete] watching %s/%s", namespace, name)
    elapsed = 0
    last_error = ""
    last_error_since = 0

    while elapsed < _MAX_WAIT:
        await asyncio.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL

        osc = _get_osc(namespace, name)
        if osc is None:
            log.info("[force-delete] %s/%s gone — done", namespace, name)
            return

        error = _deletion_error(osc)
        if not error:
            continue

        log.warning("[force-delete] %s stuck: %s", name, error[:160])

        if error != last_error:
            last_error = error
            last_error_since = elapsed

        stuck_for = elapsed - last_error_since

        if "RouterInterfaceInUseByFloatingIP" in error:
            router_id = _router_id_from_error(error)
            if router_id:
                await _release_fips(namespace, name, router_id)
                continue

        if stuck_for >= _FORCE_AFTER:
            log.warning("[force-delete] force-patching finalizers for %s (%ds stuck)", name, stuck_for)
            _strip_finalizers(namespace, name)
            return

    log.error("[force-delete] gave up on %s after %ds", name, _MAX_WAIT)


# ---------------------------------------------------------------------------

def _get_osc(namespace: str, name: str) -> dict | None:
    try:
        return _custom.get_namespaced_custom_object(
            CAPO_GROUP, CAPO_VERSION, namespace, "openstackclusters", name
        )
    except ApiException as e:
        if e.status == 404:
            return None
        raise


def _deletion_error(osc: dict) -> str:
    for c in osc.get("status", {}).get("conditions", []):
        if c.get("status") == "False" and c.get("message"):
            return c["message"]
    return ""


def _router_id_from_error(error: str) -> str:
    m = re.search(r"routers/([0-9a-f-]{36})", error)
    return m.group(1) if m else ""


async def _release_fips(namespace: str, cluster_name: str, router_id: str) -> None:
    log.info("[force-delete] releasing FIPs on router %s for %s", router_id, cluster_name)
    clouds_yaml, cloud_name = _load_cloud_config(namespace, cluster_name)
    if not clouds_yaml:
        log.error("[force-delete] no cloud config for %s — skipping FIP release", cluster_name)
        return

    tmp = None
    try:
        import openstack
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(clouds_yaml)
            tmp = f.name

        conn = openstack.connect(
            cloud=cloud_name,
            config=openstack.config.OpenStackConfig(config_files=[tmp]),
        )

        # Safety: only touch a router CAPO created for this cluster.
        # CAPO names routers "<cluster-name>-<suffix>" and tags them
        # "capi-cluster-<cluster-name>". Abort if neither matches.
        router = conn.network.get_router(router_id)
        router_name = (router.name or "").lower()
        router_tags = router.tags or []
        owned = (
            cluster_name.lower() in router_name
            or f"capi-cluster-{cluster_name}" in router_tags
        )
        if not owned:
            log.error(
                "[force-delete] SAFETY ABORT — router %s (name=%r tags=%r) "
                "does not belong to cluster %s — refusing to touch it",
                router_id, router.name, router_tags, cluster_name,
            )
            return

        for fip in conn.network.ips(router_id=router_id):
            log.info("[force-delete] deleting FIP %s (%s)", fip.id, fip.floating_ip_address)
            try:
                conn.network.delete_ip(fip.id)
            except Exception as exc:
                log.warning("[force-delete] FIP %s delete failed: %s", fip.id, exc)
    except Exception as exc:
        log.error("[force-delete] openstack SDK error: %s", exc)
    finally:
        if tmp:
            os.unlink(tmp)


def _load_cloud_config(namespace: str, cluster_name: str) -> tuple[str, str]:
    try:
        osc = _custom.get_namespaced_custom_object(
            CAPO_GROUP, CAPO_VERSION, namespace, "openstackclusters", cluster_name
        )
        ref         = osc.get("spec", {}).get("identityRef", {})
        cloud_name  = ref.get("cloudName", "")
        secret_name = ref.get("name", "")
        if secret_name:
            secret  = _core.read_namespaced_secret(secret_name, namespace)
            encoded = (secret.data or {}).get("clouds.yaml") or (secret.data or {}).get("clouds.yml", "")
            if encoded:
                return base64.b64decode(encoded).decode(), cloud_name
    except Exception as exc:
        log.warning("[force-delete] _load_cloud_config error: %s", exc)
    return "", ""


def _strip_finalizers(namespace: str, name: str) -> None:
    patch = {"metadata": {"finalizers": []}}
    for group, version, plural in [
        (CAPO_GROUP, CAPO_VERSION, "openstackclusters"),
        (CAPI_GROUP, CAPI_VERSION, "clusters"),
    ]:
        try:
            _custom.patch_namespaced_custom_object(group, version, namespace, plural, name, patch)
            log.info("[force-delete] stripped finalizers from %s/%s (%s)", namespace, name, plural)
        except ApiException as exc:
            if exc.status != 404:
                log.warning("[force-delete] patch %s error: %s", plural, exc)
