"""Deterministic demo mode.

The recruiter-facing demo must run with `docker compose up` only: no
OpenStack credentials, no management-cluster kubeconfig, no kubectl.  This
module replaces the infrastructure-facing functions with small fakes while
leaving the real network validation, database, auth and UI code untouched.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta

from app.config import settings


DEMO_USED_NETWORKS = [
    ipaddress.ip_network("10.6.0.0/24"),
    ipaddress.ip_network("10.7.0.0/24"),
]


def _now_minus(minutes: int) -> str:
    return (datetime.utcnow() - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _machines(namespace: str, cluster_name: str) -> list[dict]:
    if cluster_name == "demo-dev":
        return [
            {"name": f"{cluster_name}-cp-0", "phase": "Running", "ready": True, "flavor": "k8s.master.small"},
            {"name": f"{cluster_name}-worker-0", "phase": "Failed", "ready": False, "flavor": "k8s.node.small"},
        ]
    workers = 3 if cluster_name == "demo-prod" else 2
    machines = [
        {"name": f"{cluster_name}-cp-{i}", "phase": "Running", "ready": True, "flavor": "k8s.master.medium"}
        for i in range(3 if cluster_name == "demo-prod" else 1)
    ]
    machines += [
        {"name": f"{cluster_name}-worker-{i}", "phase": "Running", "ready": True, "flavor": "k8s.node.medium"}
        for i in range(workers)
    ]
    return machines


def _events(namespace: str, cluster_name: str) -> list[dict]:
    return [
        {"reason": "Provisioned", "message": "Cluster infrastructure is ready", "type": "Normal", "timestamp": _now_minus(42)},
        {"reason": "KubeconfigReady", "message": "Workload kubeconfig secret created", "type": "Normal", "timestamp": _now_minus(41)},
        {"reason": "PostInstallComplete", "message": "Calico, OpenStack CCM and Cinder CSI are ready", "type": "Normal", "timestamp": _now_minus(38)},
    ]


def _workload_events(namespace: str, cluster_name: str, since_minutes: int = 60, limit: int = 200) -> list[dict]:
    return [
        {"namespace": "kube-system", "reason": "Started", "message": "Started container csi-cinder-controllerplugin", "type": "Normal", "object": "Pod/csi-cinder-controllerplugin-0", "timestamp": _now_minus(35), "count": 1},
        {"namespace": "ingress-nginx", "reason": "Scheduled", "message": "Successfully assigned ingress-nginx/controller-0 to demo-worker-1", "type": "Normal", "object": "Pod/ingress-nginx-controller-0", "timestamp": _now_minus(32), "count": 1},
        {"namespace": "monitoring", "reason": "Pulled", "message": "Container image prometheus:v2.54.1 already present", "type": "Normal", "object": "Pod/prometheus-0", "timestamp": _now_minus(28), "count": 1},
        {"namespace": "default", "reason": "BackOff", "message": "Back-off restarting failed container demo-api (demo data)", "type": "Warning", "object": "Pod/demo-api-7d9f", "timestamp": _now_minus(12), "count": 4},
    ][:limit]


def _namespaces(namespace: str, cluster_name: str) -> list[str]:
    return ["default", "ingress-nginx", "kube-system", "monitoring"]


def _resources(namespace: str, cluster_name: str, ns: str, kind: str) -> list[dict]:
    age = _now_minus(40)
    if kind == "pods":
        return [
            {"name": "demo-api-7d9f-abc12", "status": "Running", "ready": "1/1", "restarts": 0, "node": "demo-worker-1", "age": age, "containers": ["api"]},
            {"name": "demo-api-7d9f-def34", "status": "Running", "ready": "1/1", "restarts": 0, "node": "demo-worker-2", "age": age, "containers": ["api"]},
            {"name": "prometheus-0", "status": "Running", "ready": "1/1", "restarts": 0, "node": "demo-worker-1", "age": age, "containers": ["prometheus"]},
        ]
    if kind == "deployments":
        return [
            {"name": "demo-api", "ready": "2/2", "age": age},
            {"name": "ingress-nginx-controller", "ready": "1/1", "age": age},
        ]
    if kind == "services":
        return [
            {"name": "demo-api", "type": "ClusterIP", "cluster_ip": "10.96.14.22", "ports": "80/TCP", "age": age},
            {"name": "ingress-nginx-controller", "type": "LoadBalancer", "cluster_ip": "10.96.88.10", "ports": "80/TCP, 443/TCP", "age": age},
        ]
    if kind == "pvcs":
        return [
            {"name": "prometheus-data", "status": "Bound", "capacity": "20Gi", "storage_class": "cinder", "age": age},
        ]
    return []


def _pod_logs(namespace: str, cluster_name: str, ns: str, pod: str, container: str, lines: int) -> str:
    return "\n".join([
        f"2026-11-11T09:00:01Z demo mode: logs for {ns}/{pod}",
        "2026-11-11T09:00:02Z server listening on :8080",
        "2026-11-11T09:00:03Z readiness probe OK",
        "2026-11-11T09:00:04Z GET /healthz 200 1ms",
        "2026-11-11T09:00:05Z GET /api/clusters 200 4ms",
    ])


def _kubeconfig(namespace: str, cluster_name: str) -> str:
    return (
        "# Demo kubeconfig generated by CAPI Platform UI in DEMO_MODE.\n"
        "# It is not a real credential and cannot connect to a cluster.\n"
        "apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\n"
    )


def _ensure_cloud_secret(namespace: str, os_cloud: str, clouds_yaml_content: str) -> None:
    return None


def _create_cluster(namespace: str, params: dict) -> dict:
    return {"created": [], "demo": True, "cluster": params.get("cluster_name")}


def _delete_cluster(namespace: str, name: str) -> None:
    return None


def _scale_workers(namespace: str, cluster_name: str, worker_count: int) -> None:
    return None


def _upgrade_cluster(namespace: str, cluster_name: str, k8s_version: str) -> None:
    return None


async def _noop_async(*args, **kwargs) -> None:
    return None


def _noop(*args, **kwargs) -> None:
    return None


def _load_clouds_yaml() -> tuple[str, str]:
    return (
        "# Demo clouds.yaml generated by CAPI Platform UI in DEMO_MODE.\n"
        "clouds:\n  demo-cloud: {}\n",
        "demo-cloud",
    )


def enable_demo() -> None:
    """Patch infrastructure adapters with deterministic demo implementations."""
    if not settings.demo_mode:
        return

    from app.services import capi, force_delete, network, post_install
    from app.routers import clusters

    capi.list_clusters = lambda namespace: []
    capi.get_cluster = lambda namespace, name: {"metadata": {"name": name}, "status": {"phase": "Provisioned"}}
    capi.list_machines = _machines
    capi.get_kubeconfig = _kubeconfig
    capi.get_cluster_events = _events
    capi.get_workload_events = _workload_events
    capi.get_workload_namespaces = _namespaces
    capi.get_workload_resources = _resources
    capi.get_pod_logs = _pod_logs
    capi.ensure_cloud_secret = _ensure_cloud_secret
    capi.create_cluster = _create_cluster
    capi.delete_cluster = _delete_cluster
    capi.scale_workers = _scale_workers
    capi.upgrade_cluster = _upgrade_cluster

    network.get_used_networks = lambda: DEMO_USED_NETWORKS

    post_install.schedule_post_install = _noop
    force_delete.watch_and_force_delete = _noop_async
    clusters._load_clouds_yaml = _load_clouds_yaml
