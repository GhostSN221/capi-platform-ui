from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException
from jinja2 import Environment, FileSystemLoader
import yaml, logging, base64

log = logging.getLogger(__name__)

try:
    k8s_config.load_incluster_config()
    log.info("In-cluster k8s config loaded")
except Exception:
    k8s_config.load_kube_config()
    log.info("Local kubeconfig loaded")

_custom = client.CustomObjectsApi()
_core   = client.CoreV1Api()
_jinja  = Environment(loader=FileSystemLoader("app/templates"))

CAPI_GROUP   = "cluster.x-k8s.io"
CAPI_VERSION = "v1beta2"


def _render_template(name: str, ctx: dict) -> list[dict]:
    tpl = _jinja.get_template(name)
    raw = tpl.render(**ctx)
    return list(yaml.safe_load_all(raw))


def ensure_cloud_secret(namespace: str, os_cloud: str, clouds_yaml_content: str) -> None:
    """Create the openstack cloud secret in the namespace if it doesn't already exist."""
    secret_name = f"{os_cloud}-cloud-config"
    try:
        _core.read_namespaced_secret(secret_name, namespace)
        log.info("Secret %s already exists in %s", secret_name, namespace)
    except ApiException as e:
        if e.status != 404:
            raise
        log.info("Creating secret %s in %s", secret_name, namespace)
        encoded = base64.b64encode(clouds_yaml_content.encode()).decode()
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=secret_name, namespace=namespace),
            data={
                "clouds.yaml": encoded,
                "cacert": "",
            },
        )
        try:
            _core.create_namespaced_secret(namespace, secret)
        except ApiException as create_err:
            if create_err.status != 409:
                raise
            log.info("Secret %s was created concurrently, ignoring", secret_name)


def create_cluster(namespace: str, params: dict) -> dict:
    manifests = _render_template("cluster_template.yaml.j2", params)
    results = []
    for m in manifests:
        grp, ver = m["apiVersion"].split("/")
        kind = m["kind"]
        plural = kind.lower() + "s"
        try:
            r = _custom.create_namespaced_custom_object(grp, ver, namespace, plural, m)
            results.append({"kind": kind, "name": r["metadata"]["name"]})
        except ApiException as e:
            log.error("create_cluster error: %s", e)
            raise
    return {"created": results}


def list_clusters(namespace: str) -> list[dict]:
    res = _custom.list_namespaced_custom_object(
        CAPI_GROUP, CAPI_VERSION, namespace, "clusters"
    )
    return [
        {
            "name":   c["metadata"]["name"],
            "phase":  c.get("status", {}).get("phase", "Unknown"),
            "ready":  c.get("status", {}).get("infrastructureReady", False),
            "k8s_version": c["spec"].get("topology", {}).get("version", ""),
        }
        for c in res.get("items", [])
    ]


def get_cluster(namespace: str, name: str) -> dict:
    return _custom.get_namespaced_custom_object(
        CAPI_GROUP, CAPI_VERSION, namespace, "clusters", name
    )


def delete_cluster(namespace: str, name: str) -> None:
    _custom.delete_namespaced_custom_object(
        CAPI_GROUP, CAPI_VERSION, namespace, "clusters", name
    )


def list_machines(namespace: str, cluster_name: str) -> list[dict]:
    res = _custom.list_namespaced_custom_object(
        CAPI_GROUP, CAPI_VERSION, namespace, "machines",
        label_selector=f"cluster.x-k8s.io/cluster-name={cluster_name}"
    )
    return [
        {
            "name":   m["metadata"]["name"],
            "phase":  m.get("status", {}).get("phase", "Unknown"),
            "ready":  m.get("status", {}).get("nodeRef") is not None,
            "flavor": m["spec"].get("infrastructureRef", {}).get("name", ""),
        }
        for m in res.get("items", [])
    ]


def get_kubeconfig(namespace: str, cluster_name: str) -> str:
    secret_name = f"{cluster_name}-kubeconfig"
    secret = _core.read_namespaced_secret(secret_name, namespace)
    return base64.b64decode(secret.data["value"]).decode()


def get_cluster_events(namespace: str, cluster_name: str) -> list[dict]:
    """Return recent events for the given cluster name."""
    res = _core.list_namespaced_event(
        namespace,
        field_selector=f"involvedObject.name={cluster_name}"
    )
    events = []
    for e in res.items:
        ts = None
        if e.last_timestamp:
            ts = e.last_timestamp.isoformat()
        elif e.event_time:
            ts = e.event_time.isoformat()
        events.append({
            "reason":    e.reason or "",
            "message":   e.message or "",
            "type":      e.type or "Normal",
            "timestamp": ts,
        })
    return events


def get_workload_events(namespace: str, cluster_name: str, since_minutes: int = 60, limit: int = 200) -> list[dict]:
    """Return events from inside the workload cluster itself (all namespaces)."""
    import tempfile, os
    from datetime import datetime, timezone, timedelta
    kc_content = get_kubeconfig(namespace, cluster_name)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(kc_content)
        kc_path = f.name
    try:
        wl_config = k8s_config.new_client_from_config(config_file=kc_path)
        wl_core = client.CoreV1Api(api_client=wl_config)
        res = wl_core.list_event_for_all_namespaces()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        events = []
        for e in res.items:
            raw_ts = e.last_timestamp or e.event_time
            if raw_ts is None:
                continue
            # kubernetes returns timezone-aware datetime
            ts_dt = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=timezone.utc)
            if ts_dt < cutoff:
                continue
            events.append({
                "namespace": e.metadata.namespace or "",
                "reason":    e.reason or "",
                "message":   e.message or "",
                "type":      e.type or "Normal",
                "object":    f"{e.involved_object.kind}/{e.involved_object.name}" if e.involved_object else "",
                "timestamp": ts_dt.isoformat(),
                "count":     e.count or 1,
            })
        events.sort(key=lambda x: x["timestamp"], reverse=True)
        return events[:limit]
    finally:
        os.unlink(kc_path)


def _wl_client(namespace: str, cluster_name: str):
    """Return (CoreV1Api, AppsV1Api, kc_path) for the workload cluster. Caller must delete kc_path."""
    import tempfile, os
    kc_content = get_kubeconfig(namespace, cluster_name)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(kc_content)
        kc_path = f.name
    cfg = k8s_config.new_client_from_config(config_file=kc_path)
    core = client.CoreV1Api(api_client=cfg)
    apps = client.AppsV1Api(api_client=cfg)
    return core, apps, kc_path


def get_workload_namespaces(namespace: str, cluster_name: str) -> list[str]:
    import os
    core, _, kc_path = _wl_client(namespace, cluster_name)
    try:
        res = core.list_namespace()
        return sorted(ns.metadata.name for ns in res.items)
    finally:
        os.unlink(kc_path)


def get_workload_resources(namespace: str, cluster_name: str, ns: str, kind: str) -> list[dict]:
    import os
    core, apps, kc_path = _wl_client(namespace, cluster_name)
    try:
        items = []
        if kind == "pods":
            res = core.list_namespaced_pod(ns)
            for p in res.items:
                phase = p.status.phase or "Unknown"
                ready_c = sum(1 for c in (p.status.container_statuses or []) if c.ready)
                total_c = len(p.spec.containers)
                restarts = sum(c.restart_count for c in (p.status.container_statuses or []))
                containers = [c.name for c in p.spec.containers]
                items.append({
                    "name": p.metadata.name,
                    "status": phase,
                    "ready": f"{ready_c}/{total_c}",
                    "restarts": restarts,
                    "node": p.spec.node_name or "—",
                    "age": p.metadata.creation_timestamp.isoformat() if p.metadata.creation_timestamp else None,
                    "containers": containers,
                })
        elif kind == "deployments":
            res = apps.list_namespaced_deployment(ns)
            for d in res.items:
                ready = d.status.ready_replicas or 0
                desired = d.spec.replicas or 0
                items.append({
                    "name": d.metadata.name,
                    "ready": f"{ready}/{desired}",
                    "age": d.metadata.creation_timestamp.isoformat() if d.metadata.creation_timestamp else None,
                })
        elif kind == "services":
            res = core.list_namespaced_service(ns)
            for s in res.items:
                cluster_ip = s.spec.cluster_ip or "—"
                ports = ", ".join(
                    f"{p.port}/{p.protocol}" for p in (s.spec.ports or [])
                )
                items.append({
                    "name": s.metadata.name,
                    "type": s.spec.type or "—",
                    "cluster_ip": cluster_ip,
                    "ports": ports or "—",
                    "age": s.metadata.creation_timestamp.isoformat() if s.metadata.creation_timestamp else None,
                })
        elif kind == "pvcs":
            res = core.list_namespaced_persistent_volume_claim(ns)
            for pvc in res.items:
                items.append({
                    "name": pvc.metadata.name,
                    "status": pvc.status.phase or "—",
                    "capacity": (pvc.status.capacity or {}).get("storage", "—"),
                    "storage_class": pvc.spec.storage_class_name or "—",
                    "age": pvc.metadata.creation_timestamp.isoformat() if pvc.metadata.creation_timestamp else None,
                })
        return items
    finally:
        os.unlink(kc_path)


def get_pod_logs(namespace: str, cluster_name: str, ns: str, pod: str, container: str, lines: int) -> str:
    import os
    core, _, kc_path = _wl_client(namespace, cluster_name)
    try:
        return core.read_namespaced_pod_log(
            pod, ns,
            container=container or None,
            tail_lines=lines,
            timestamps=True,
        )
    finally:
        os.unlink(kc_path)


def scale_workers(namespace: str, cluster_name: str, worker_count: int) -> None:
    _custom.patch_namespaced_custom_object(
        "cluster.x-k8s.io", "v1beta2", namespace,
        "machinedeployments", f"{cluster_name}-workers",
        {"spec": {"replicas": worker_count}},
    )


def upgrade_cluster(namespace: str, cluster_name: str, k8s_version: str) -> None:
    _custom.patch_namespaced_custom_object(
        "controlplane.cluster.x-k8s.io", "v1beta2", namespace,
        "kubeadmcontrolplanes", f"{cluster_name}-cp",
        {"spec": {"version": k8s_version}},
    )
    _custom.patch_namespaced_custom_object(
        "cluster.x-k8s.io", "v1beta2", namespace,
        "machinedeployments", f"{cluster_name}-workers",
        {"spec": {"template": {"spec": {"version": k8s_version}}}},
    )
