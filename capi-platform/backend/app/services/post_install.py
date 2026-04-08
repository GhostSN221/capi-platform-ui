"""
Post-cluster-creation installer.
Runs in a background thread: waits for the workload cluster kubeconfig,
then deploys OpenStack CCM + Cinder CSI Driver so the cluster has
cloud-controller integration and persistent storage out of the box.
"""

import base64
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass

import yaml

log = logging.getLogger(__name__)

# cloud-provider-openstack v1.31.1 — compatible with k8s 1.29 / 1.30 / 1.31
_REPO = (
    "https://raw.githubusercontent.com/kubernetes/cloud-provider-openstack"
    "/refs/tags/v1.31.1/manifests"
)

_CALICO_URL = (
    "https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml"
)

_CCM_URLS = [
    f"{_REPO}/controller-manager/openstack-cloud-controller-manager-ds.yaml",
]

_CSI_URLS = [
    f"{_REPO}/cinder-csi-plugin/cinder-csi-controllerplugin-rbac.yaml",
    f"{_REPO}/cinder-csi-plugin/cinder-csi-controllerplugin.yaml",
    f"{_REPO}/cinder-csi-plugin/cinder-csi-nodeplugin-rbac.yaml",
    f"{_REPO}/cinder-csi-plugin/cinder-csi-nodeplugin.yaml",
]

_STORAGE_CLASS = """
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: cinder
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: cinder.csi.openstack.org
allowVolumeExpansion: true
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
"""

# Locate kubectl binary
_KUBECTL = os.environ.get("KUBECTL_PATH", "/usr/local/bin/kubectl")


@dataclass
class TenantInfo:
    """Snapshot of tenant fields needed by the post-installer (safe to pass across threads)."""
    namespace: str
    os_cloud: str
    external_network_id: str
    clouds_yaml: str


# ---------------------------------------------------------------------------
# cloud.conf builder
# ---------------------------------------------------------------------------

def build_cloud_conf(tenant: TenantInfo) -> str:
    """Generate an OpenStack cloud.conf.
    Reads from the CAPO k8s secret first (has real password),
    falls back to tenant.clouds_yaml.
    """
    from kubernetes import client as k8s_client
    import base64 as _b64

    # Try to read credentials from the existing CAPO secret (most reliable)
    raw_yaml = None
    try:
        core = k8s_client.CoreV1Api()
        secret = core.read_namespaced_secret(
            f"{tenant.os_cloud}-cloud-config", tenant.namespace
        )
        encoded = secret.data.get("clouds.yaml") or secret.data.get("clouds.yml", "")
        if encoded:
            raw_yaml = _b64.b64decode(encoded).decode()
    except Exception:
        pass

    clouds = yaml.safe_load(raw_yaml or tenant.clouds_yaml)
    # Try both the tenant os_cloud name and 'openstack' fallback
    cloud_key = tenant.os_cloud if tenant.os_cloud in clouds.get("clouds", {}) else list(clouds["clouds"].keys())[0]
    cloud = clouds["clouds"][cloud_key]
    auth = cloud["auth"]
    region = cloud.get("region_name", "RegionOne")

    project_name = auth.get("project_name") or auth.get("tenant_name", "")
    domain_name = (
        auth.get("user_domain_name")
        or auth.get("project_domain_name")
        or "Default"
    )

    return (
        "[Global]\n"
        f"auth-url={auth['auth_url']}\n"
        f"username={auth.get('username', '')}\n"
        f"password={auth.get('password', '')}\n"
        f"tenant-name={project_name}\n"
        f"domain-name={domain_name}\n"
        f"region={region}\n"
        "insecure=true\n"
        "\n"
        "[LoadBalancer]\n"
        "use-octavia=true\n"
        f"floating-network-id={tenant.external_network_id}\n"
        "\n"
        "[BlockStorage]\n"
        "bs-version=v3\n"
    )


# ---------------------------------------------------------------------------
# kubectl helpers
# ---------------------------------------------------------------------------

def _kubectl(kubeconfig_path: str, args: list, stdin: str | None = None) -> str:
    cmd = [_KUBECTL, "--kubeconfig", kubeconfig_path] + args
    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout


def _apply_url(kubeconfig_path: str, url: str) -> None:
    log.info("kubectl apply -f %s", url)
    _kubectl(kubeconfig_path, ["apply", "--validate=false", "-f", url])


def _apply_yaml(kubeconfig_path: str, content: str) -> None:
    _kubectl(kubeconfig_path, ["apply", "--validate=false", "-f", "-"], stdin=content)


# ---------------------------------------------------------------------------
# Main installer
# ---------------------------------------------------------------------------

def _create_cloud_config_secret(kubeconfig_path: str, cloud_conf: str) -> None:
    encoded = base64.b64encode(cloud_conf.encode()).decode()
    secret_yaml = (
        "apiVersion: v1\n"
        "kind: Secret\n"
        "metadata:\n"
        "  name: cloud-config\n"
        "  namespace: kube-system\n"
        "type: Opaque\n"
        "data:\n"
        f"  cloud.conf: {encoded}\n"
    )
    _apply_yaml(kubeconfig_path, secret_yaml)


def install_ccm_and_csi(kubeconfig_str: str, cloud_conf: str) -> None:
    """Apply CCM + Cinder CSI + StorageClass to the workload cluster."""
    kf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    kf.write(kubeconfig_str)
    kf.close()
    kp = kf.name

    try:
        log.info("Deploying Calico CNI")
        _apply_url(kp, _CALICO_URL)

        log.info("Creating cloud-config secret in kube-system")
        _create_cloud_config_secret(kp, cloud_conf)

        log.info("Deploying OpenStack Cloud Controller Manager")
        for url in _CCM_URLS:
            _apply_url(kp, url)

        # Apply RBAC immediately after CCM manifest so the pod doesn't crash on first start
        log.info("Fixing CCM RBAC permissions")
        for cmd in [
            ["create", "rolebinding", "-n", "kube-system",
             "cloud-controller-manager:extension-apiserver-authentication-reader",
             "--role=extension-apiserver-authentication-reader",
             "--serviceaccount=kube-system:cloud-controller-manager"],
            ["create", "clusterrolebinding", "cloud-controller-manager",
             "--clusterrole=cluster-admin",
             "--serviceaccount=kube-system:cloud-controller-manager"],
        ]:
            try:
                _kubectl(kp, cmd)
            except RuntimeError as e:
                if "already exists" not in str(e):
                    raise

        log.info("Deploying Cinder CSI Driver")
        for url in _CSI_URLS:
            _apply_url(kp, url)

        log.info("Creating cinder StorageClass (default)")
        _apply_yaml(kp, _STORAGE_CLASS)

        log.info("Calico + CCM + Cinder CSI installation complete")
    finally:
        os.unlink(kp)


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------

def _wait_for_kubeconfig(namespace: str, cluster_name: str, max_wait: int = 1800) -> str:
    """Poll the management cluster until the workload kubeconfig secret appears."""
    from app.services.capi import get_kubeconfig

    waited = 0
    while waited < max_wait:
        try:
            kc = get_kubeconfig(namespace, cluster_name)
            if kc:
                return kc
        except Exception:
            pass
        time.sleep(30)
        waited += 30

    raise TimeoutError(
        f"Kubeconfig for {cluster_name} not available after {max_wait // 60} minutes"
    )


def _wait_for_api_server(kubeconfig_path: str, max_wait: int = 600) -> None:
    """Wait until the workload cluster API server accepts connections."""
    waited = 0
    while waited < max_wait:
        result = subprocess.run(
            [_KUBECTL, "--kubeconfig", kubeconfig_path,
             "get", "nodes", "--request-timeout=10s"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            log.info("[post-install] API server ready")
            return
        log.info("[post-install] API server not ready yet, retrying in 20s... (%s)", result.stderr.strip()[:80])
        time.sleep(20)
        waited += 20

    raise TimeoutError("API server not reachable after 10 minutes")


def schedule_post_install(cluster_name: str, tenant: TenantInfo) -> None:
    """Spawn a daemon thread that installs CCM+CSI once the cluster is ready."""

    def _run() -> None:
        log.info("[post-install] Waiting for %s/%s kubeconfig ...", tenant.namespace, cluster_name)
        try:
            kubeconfig_str = _wait_for_kubeconfig(tenant.namespace, cluster_name)
            log.info("[post-install] Kubeconfig ready, waiting for API server on %s ...", cluster_name)

            kf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
            kf.write(kubeconfig_str)
            kf.close()
            try:
                _wait_for_api_server(kf.name)
            finally:
                os.unlink(kf.name)

            log.info("[post-install] Installing addons on %s", cluster_name)
            cloud_conf = build_cloud_conf(tenant)
            install_ccm_and_csi(kubeconfig_str, cloud_conf)
            log.info("[post-install] Done for %s", cluster_name)
        except Exception as exc:
            log.error("[post-install] Failed for %s: %s", cluster_name, exc)

    t = threading.Thread(target=_run, daemon=True, name=f"post-install-{cluster_name}")
    t.start()
    log.info("[post-install] Background thread started for %s", cluster_name)
