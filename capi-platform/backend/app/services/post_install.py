"""
Post-cluster-creation installer.
Runs in a background thread: waits for the workload cluster kubeconfig,
then deploys the full addon stack so the cluster is production-ready:
  - Calico CNI (networking)
  - OpenStack CCM (node lifecycle + LoadBalancer via Octavia)
  - Cinder CSI Driver (persistent volumes)
  - ingress-nginx (HTTP/HTTPS routing via un seul Octavia LB)
"""

import base64
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
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

# ingress-nginx v1.11.3 — compatible with k8s 1.29 / 1.30 / 1.31 / 1.34
# "cloud" variant : crée un Service type=LoadBalancer → Octavia LB automatique
_INGRESS_NGINX_URL = (
    "https://raw.githubusercontent.com/kubernetes/ingress-nginx"
    "/controller-v1.11.3/deploy/static/provider/cloud/deploy.yaml"
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

def build_cloud_conf(tenant: TenantInfo, cluster_name: str = "") -> str:
    """Generate an OpenStack cloud.conf.
    Reads from the CAPO k8s secret first (has real password),
    falls back to tenant.clouds_yaml.
    cluster_name is injected into [LoadBalancer] so each cluster gets its own
    Octavia LB namespace and never hijacks another cluster's load balancers.
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

    lb_cluster_name = cluster_name or tenant.os_cloud
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
        f"cluster-name={lb_cluster_name}\n"
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


def _set_env(env: list, name: str, value: str) -> None:
    """Set (or append) a container env var in a Kubernetes manifest."""
    for item in env:
        if item.get("name") == name:
            item["value"] = value
            return
    env.append({"name": name, "value": value})


def _install_calico(kubeconfig_path: str) -> None:
    """Installe Calico adapté à OpenStack (VXLAN + pod CIDR + MTU).

    Le manifest upstream ne peut pas être appliqué tel quel :
      - son IPPool par défaut est 192.168.0.0/16, qui chevauche l'on-prem
        (DB 192.168.120.x, Nutanix 192.168.10.x) ;
      - il active IPIP (Always) : sur OpenStack le port security interdit le
        routage direct des IP de pods, donc CrossSubnet casse le pod->pod ;
      - il ignore le MTU de l'underlay (1450 sur OpenStack).
    """
    from app.config import settings

    log.info("Downloading Calico manifest from %s", _CALICO_URL)
    with urllib.request.urlopen(_CALICO_URL, timeout=120) as resp:
        raw = resp.read().decode()

    docs = [d for d in yaml.safe_load_all(raw) if d]
    node_ds_found = False

    for doc in docs:
        kind = doc.get("kind")
        name = (doc.get("metadata") or {}).get("name")

        if kind == "DaemonSet" and name == "calico-node":
            containers = doc["spec"]["template"]["spec"]["containers"]
            node = next((c for c in containers if c.get("name") == "calico-node"), None)
            if node is None:
                raise RuntimeError("Calico manifest: container 'calico-node' introuvable")
            env = node.setdefault("env", [])
            _set_env(env, "CALICO_IPV4POOL_CIDR", settings.pod_cidr)
            _set_env(env, "CALICO_IPV4POOL_IPIP", settings.calico_ipip_mode)
            _set_env(env, "CALICO_IPV4POOL_VXLAN", settings.calico_vxlan_mode)
            node_ds_found = True

        elif kind == "ConfigMap" and name == "calico-config":
            data = doc.setdefault("data", {})
            data["veth_mtu"] = str(settings.calico_mtu)

    if not node_ds_found:
        raise RuntimeError("Calico manifest: DaemonSet calico-node introuvable")

    log.info(
        "Calico: pod_cidr=%s ipip=%s vxlan=%s veth_mtu=%s",
        settings.pod_cidr,
        settings.calico_ipip_mode,
        settings.calico_vxlan_mode,
        settings.calico_mtu,
    )
    _apply_yaml(kubeconfig_path, "\n---\n".join(yaml.safe_dump(d) for d in docs))


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


def _patch_coredns_tolerations(kubeconfig_path: str) -> None:
    """Patch CoreDNS Deployment to tolerate CAPI + cloud-provider uninitialized taints.

    Uses JSON patch (replace) instead of strategic merge to avoid the k8s
    strategic-merge bug where the entire tolerations array gets replaced by
    only the new entry — which would strip the existing CriticalAddonsOnly toleration.
    """
    tolerations = [
        {"key": "node.cloudprovider.kubernetes.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
        {"key": "node.cluster.x-k8s.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
        {"key": "CriticalAddonsOnly", "operator": "Exists"},
    ]
    patch = json.dumps([{"op": "replace", "path": "/spec/template/spec/tolerations", "value": tolerations}])
    try:
        _kubectl(kubeconfig_path, [
            "patch", "deployment", "coredns",
            "-n", "kube-system",
            "--type=json",
            "--patch", patch,
        ])
        log.info("Patched CoreDNS with uninitialized taint tolerations")
    except RuntimeError as e:
        log.warning("Could not patch CoreDNS tolerations: %s", e)


def _patch_ccm_tolerations(kubeconfig_path: str) -> None:
    """Set the full toleration list on the CCM DaemonSet.

    The official manifest has tolerations for cloudprovider + master/control-plane.
    We add node.cluster.x-k8s.io/uninitialized so the CCM pod can land on nodes
    before CAPI finishes initialising them.
    Uses JSON replace to avoid strategic-merge stripping existing tolerations.
    """
    tolerations = [
        {"key": "node.cloudprovider.kubernetes.io/uninitialized", "value": "true", "effect": "NoSchedule"},
        {"key": "node-role.kubernetes.io/master", "effect": "NoSchedule"},
        {"key": "node-role.kubernetes.io/control-plane", "effect": "NoSchedule"},
        {"key": "node.cluster.x-k8s.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
        {"key": "CriticalAddonsOnly", "operator": "Exists"},
    ]
    patch = json.dumps([{"op": "replace", "path": "/spec/template/spec/tolerations", "value": tolerations}])
    try:
        _kubectl(kubeconfig_path, [
            "patch", "daemonset", "openstack-cloud-controller-manager",
            "-n", "kube-system",
            "--type=json",
            "--patch", patch,
        ])
        log.info("Patched CCM DaemonSet with full toleration set")
    except RuntimeError as e:
        log.warning("Could not patch CCM DaemonSet tolerations: %s", e)


def _patch_daemonset_tolerations(kubeconfig_path: str, name: str, namespace: str, tolerations: list) -> None:
    """Merge tolerations into a DaemonSet via strategic-merge patch (appends, does not replace)."""
    patch = json.dumps({"spec": {"template": {"spec": {"tolerations": tolerations}}}})
    try:
        _kubectl(kubeconfig_path, [
            "patch", "daemonset", name, "-n", namespace,
            "--type=strategic", "--patch", patch,
        ])
        log.info("Patched daemonset/%s with uninitialized taint tolerations", name)
    except RuntimeError as e:
        log.warning("Could not patch daemonset/%s tolerations: %s", name, e)


def _patch_missing_provider_ids(kubeconfig_path: str, cluster_name: str, namespace: str) -> None:
    """Patch spec.providerID on nodes that the CCM never initialized.

    Reads providerIDs from CAPI Machine objects on the management cluster (in-cluster
    config) and writes them to the matching Kubernetes nodes on the workload cluster.
    This allows CAPI to match Machine→Node even when the CCM never ran.
    """
    from kubernetes import client as k8s_client, config as k8s_config

    try:
        k8s_config.load_incluster_config()
        custom = k8s_client.CustomObjectsApi()
        machines = custom.list_namespaced_custom_object(
            "cluster.x-k8s.io", "v1beta1", namespace, "machines",
            label_selector=f"cluster.x-k8s.io/cluster-name={cluster_name}",
        )
        provider_ids = {
            m["metadata"]["name"]: m["spec"]["providerID"]
            for m in machines.get("items", [])
            if m.get("spec", {}).get("providerID")
        }
    except Exception as exc:
        log.warning("Could not read Machine providerIDs from management cluster: %s", exc)
        return

    if not provider_ids:
        log.warning("No providerIDs found in Machine objects for cluster %s", cluster_name)
        return

    try:
        out = _kubectl(kubeconfig_path, [
            "get", "nodes",
            "-o", "jsonpath={range .items[*]}{.metadata.name}={.spec.providerID}{\"\\n\"}{end}",
        ])
        missing = [
            l.split("=")[0] for l in out.strip().splitlines()
            if "=" in l and l.split("=", 1)[1] == ""
        ]
    except RuntimeError as exc:
        log.warning("Could not list nodes for providerID patch: %s", exc)
        return

    for node in missing:
        pid = provider_ids.get(node)
        if not pid:
            log.warning("No providerID in CAPI Machine for node %s — skipping", node)
            continue
        try:
            _kubectl(kubeconfig_path, [
                "patch", "node", node, "-p", json.dumps({"spec": {"providerID": pid}}),
            ])
            log.info("Patched providerID %s on node %s", pid, node)
        except RuntimeError as exc:
            log.warning("Could not patch providerID on node %s: %s", node, exc)


def _remove_uninitialized_taints(
    kubeconfig_path: str,
    cluster_name: str = "",
    namespace: str = "",
    max_wait: int = 300,
) -> None:
    """Remove uninitialized taints after ensuring providerIDs are set.

    1. Wait up to max_wait seconds for the CCM to initialize all nodes
       (set spec.providerID + remove taints). If it finishes cleanly: done.
    2. On timeout (e.g., CCM stuck on ImagePullBackOff):
       a. Patch missing providerIDs from CAPI Machine objects so CAPI can still
          match Machine→Node without the CCM.
       b. Force-remove all uninitialized taints so pods can schedule.

    The taint suffix '-' means remove; 'not found' errors are silently ignored.
    """
    taints = [
        "node.cloudprovider.kubernetes.io/uninitialized:NoSchedule-",
        "node.cluster.x-k8s.io/uninitialized:NoSchedule-",
    ]

    def _nodes_missing_provider_id() -> list:
        out = _kubectl(kubeconfig_path, [
            "get", "nodes",
            "-o", "jsonpath={range .items[*]}{.metadata.name}={.spec.providerID}{\"\\n\"}{end}",
        ])
        return [
            l.split("=")[0] for l in out.strip().splitlines()
            if "=" in l and l.split("=", 1)[1] == ""
        ]

    # Wait for the CCM to initialize all nodes
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            missing = _nodes_missing_provider_id()
            if not missing:
                log.info("CCM initialized all nodes — no manual taint removal needed")
                return
            log.info("Waiting for CCM to initialize %d node(s): %s", len(missing), missing)
        except RuntimeError as exc:
            log.warning("Could not check node providerIDs: %s", exc)
        time.sleep(20)

    log.warning("CCM did not initialize all nodes within %ds — taking over", max_wait)

    # Step 1: patch providerIDs from CAPI so Machine→Node match still works
    if cluster_name and namespace:
        _patch_missing_provider_ids(kubeconfig_path, cluster_name, namespace)
    else:
        log.warning("cluster_name/namespace not provided — skipping providerID patch")

    # Step 2: remove all uninitialized taints so pods can schedule
    try:
        out = _kubectl(kubeconfig_path, ["get", "nodes", "-o", "jsonpath={.items[*].metadata.name}"])
        nodes = out.strip().split() if out.strip() else []
    except RuntimeError as exc:
        log.warning("Could not list nodes for taint removal: %s", exc)
        return

    for node in nodes:
        for taint in taints:
            try:
                _kubectl(kubeconfig_path, ["taint", "node", node, taint])
                log.info("Removed taint %s from %s", taint.rstrip("-"), node)
            except RuntimeError:
                pass  # taint already absent — normal once CCM has run


def install_ccm_and_csi(kubeconfig_str: str, cloud_conf: str, cluster_name: str = "", namespace: str = "") -> None:
    """Apply CCM + Cinder CSI + StorageClass to the workload cluster."""
    kf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    kf.write(kubeconfig_str)
    kf.close()
    kp = kf.name

    try:
        log.info("Deploying Calico CNI (VXLAN)")
        _install_calico(kp)
        # Strategic-merge replaces the whole tolerations array instead of appending,
        # so we include the full set: standard Calico entries + our custom ones.
        log.info("Patching calico-node DaemonSet tolerations for uninitialized nodes")
        _patch_daemonset_tolerations(kp, "calico-node", "kube-system", [
            {"effect": "NoSchedule", "operator": "Exists"},
            {"key": "CriticalAddonsOnly", "operator": "Exists"},
            {"effect": "NoExecute", "operator": "Exists"},
            {"key": "node.cloudprovider.kubernetes.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
            {"key": "node.cluster.x-k8s.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
        ])

        # Patch CoreDNS early so it can schedule on still-tainted nodes while
        # CCM initialises them. Both taints (cloudprovider + CAPI) must be
        # tolerated otherwise CoreDNS stays Pending until both are removed.
        log.info("Patching CoreDNS tolerations for uninitialized nodes")
        _patch_coredns_tolerations(kp)

        log.info("Creating cloud-config secret in kube-system")
        _create_cloud_config_secret(kp, cloud_conf)

        log.info("Deploying OpenStack Cloud Controller Manager")
        for url in _CCM_URLS:
            _apply_url(kp, url)

        # The official CCM manifest has CLUSTER_NAME=kubernetes hardcoded.
        # --cluster-name takes precedence over cloud.conf for Octavia LB naming,
        # so without this patch all clusters share the same LB name prefix and
        # the CCM errors with "multiple results where only one expected".
        if cluster_name:
            log.info("Patching CCM DaemonSet CLUSTER_NAME to %s", cluster_name)
            _kubectl(kp, [
                "patch", "daemonset", "openstack-cloud-controller-manager",
                "-n", "kube-system",
                "--type=strategic",
                "--patch", json.dumps({
                    "spec": {"template": {"spec": {"containers": [{
                        "name": "openstack-cloud-controller-manager",
                        "env": [{"name": "CLUSTER_NAME", "value": cluster_name}],
                    }]}}}
                }),
            ])

        # The official CCM manifest tolerates node.cloudprovider.kubernetes.io/uninitialized
        # but NOT node.cluster.x-k8s.io/uninitialized. Patch it so the CCM pod
        # can actually land on nodes and remove the cloud-provider taint.
        log.info("Patching CCM DaemonSet tolerations for CAPI uninitialized taint")
        _patch_ccm_tolerations(kp)

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
        log.info("Patching csi-cinder-nodeplugin DaemonSet tolerations for uninitialized nodes")
        _patch_daemonset_tolerations(kp, "csi-cinder-nodeplugin", "kube-system", [
            {"key": "node.cloudprovider.kubernetes.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
            {"key": "node.cluster.x-k8s.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
        ])

        # calico-kube-controllers and csi-cinder-controllerplugin don't tolerate
        # node.cluster.x-k8s.io/uninitialized by default → patch them too.
        # Use JSON replace so we don't accidentally strip existing tolerations.
        log.info("Patching calico-kube-controllers and csi-cinder-controllerplugin tolerations")
        for resource, extra_tolerations in [
            ("calico-kube-controllers", [
                {"key": "node.cluster.x-k8s.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
                {"key": "node.cloudprovider.kubernetes.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
                {"key": "CriticalAddonsOnly", "operator": "Exists"},
            ]),
            ("csi-cinder-controllerplugin", [
                {"key": "node.cluster.x-k8s.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
                {"key": "node.cloudprovider.kubernetes.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
            ]),
        ]:
            patch = json.dumps([{
                "op": "replace",
                "path": "/spec/template/spec/tolerations",
                "value": extra_tolerations,
            }])
            try:
                _kubectl(kp, [
                    "patch", "deployment", resource,
                    "-n", "kube-system",
                    "--type=json",
                    "--patch", patch,
                ])
                log.info("Patched deployment/%s tolerations", resource)
            except RuntimeError as e:
                log.warning("Could not patch deployment/%s tolerations: %s", resource, e)

        log.info("Creating cinder StorageClass (default)")
        _apply_yaml(kp, _STORAGE_CLASS)

        # ingress-nginx : un seul Octavia LB pour tout le trafic HTTP/HTTPS
        # Les services non-HTTP (BDD, etc.) continuent d'utiliser type=LoadBalancer
        log.info("Deploying ingress-nginx controller")
        _apply_url(kp, _INGRESS_NGINX_URL)

        # Patch ingress-nginx tolerations pour les taints CAPI/cloudprovider
        _ingress_patch = json.dumps([{
            "op": "replace",
            "path": "/spec/template/spec/tolerations",
            "value": [
                {"key": "node.cluster.x-k8s.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
                {"key": "node.cloudprovider.kubernetes.io/uninitialized", "operator": "Exists", "effect": "NoSchedule"},
            ],
        }])
        try:
            _kubectl(kp, [
                "patch", "deployment", "ingress-nginx-controller",
                "-n", "ingress-nginx",
                "--type=json", "--patch", _ingress_patch,
            ])
            log.info("Patched ingress-nginx-controller tolerations")
        except RuntimeError as e:
            log.warning("Could not patch ingress-nginx tolerations: %s", e)

        log.info("Removing uninitialized node taints (safety net if CCM delayed)")
        _remove_uninitialized_taints(kp, cluster_name=cluster_name, namespace=namespace)

        log.info("Calico + CCM + Cinder CSI + ingress-nginx installation complete")
    finally:
        os.unlink(kp)


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------

def _watch_and_patch_new_nodes(
    kubeconfig_str: str,
    cluster_name: str,
    namespace: str,
    duration: int = 2700,  # 45 min — covers 3-CP and 5-CP scale-up
) -> None:
    """Watch for nodes that join without a providerID and patch them automatically.

    KCP scales control planes one at a time: the 2nd and 3rd CP nodes join
    after the post-install is done, so the initial providerID patch misses them.
    This watcher runs in the background thread and catches late-joining nodes.
    """
    kf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    kf.write(kubeconfig_str)
    kf.close()
    kp = kf.name
    deadline = time.time() + duration
    try:
        while time.time() < deadline:
            time.sleep(30)
            try:
                out = _kubectl(kp, [
                    "get", "nodes",
                    "-o", "jsonpath={range .items[*]}{.metadata.name}={.spec.providerID}{\"\\n\"}{end}",
                ])
                missing = [
                    line.split("=")[0] for line in out.strip().splitlines()
                    if "=" in line and line.split("=", 1)[1] == ""
                ]
                if missing:
                    log.info("[node-watcher] %d node(s) without providerID: %s — patching", len(missing), missing)
                    _patch_missing_provider_ids(kp, cluster_name, namespace)
            except RuntimeError as exc:
                log.warning("[node-watcher] error checking nodes: %s", exc)
    finally:
        os.unlink(kp)


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
            cloud_conf = build_cloud_conf(tenant, cluster_name=cluster_name)
            install_ccm_and_csi(kubeconfig_str, cloud_conf, cluster_name=cluster_name, namespace=tenant.namespace)
            log.info("[post-install] Addons done for %s — starting node-watcher (45 min)", cluster_name)
            _watch_and_patch_new_nodes(kubeconfig_str, cluster_name, tenant.namespace)
            log.info("[post-install] Node-watcher done for %s", cluster_name)
        except Exception as exc:
            log.error("[post-install] Failed for %s: %s", cluster_name, exc)

    t = threading.Thread(target=_run, daemon=True, name=f"post-install-{cluster_name}")
    t.start()
    log.info("[post-install] Background thread started for %s", cluster_name)
