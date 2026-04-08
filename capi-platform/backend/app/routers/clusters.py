from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.models.tenant import Tenant
from app.schemas.cluster import ClusterCreate, ClusterOut
from app.services.auth import get_current_user
from app.services import capi
from app.services.audit import log_action
from app.services.post_install import schedule_post_install, TenantInfo
from app.models.cluster import Cluster
from datetime import datetime

router = APIRouter()


class ScaleRequest(BaseModel):
    worker_count: int


class UpgradeRequest(BaseModel):
    k8s_version: str


async def resolve_tenant(user: User, db: AsyncSession) -> Tenant:
    t = await db.get(Tenant, user.tenant_id)
    if not t:
        raise HTTPException(400, "User has no tenant assigned")
    return t


_PHASE_MAP = {
    "Provisioned":  "Ready",
    "Provisioning": "Provisioning",
    "Deleting":     "Provisioning",
    "Failed":       "Failed",
}

@router.get("/")
async def list_clusters(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    tenant = await resolve_tenant(user, db)

    # Live status from k8s
    k8s_map = {
        c["name"]: _PHASE_MAP.get(c["phase"], c["phase"])
        for c in capi.list_clusters(tenant.namespace)
    }

    # DB metadata (flavors, worker_count, etc.)
    res = await db.execute(select(Cluster).where(Cluster.tenant_id == tenant.id))
    db_clusters = res.scalars().all()

    result = []
    for c in db_clusters:
        result.append({
            "id":            c.id,
            "name":          c.name,
            "k8s_version":   c.k8s_version,
            "cp_flavor":     c.cp_flavor,
            "worker_flavor": c.worker_flavor,
            "worker_count":  c.worker_count,
            "status":        k8s_map.get(c.name, c.status),  # live > DB
            "namespace":     tenant.namespace,
            "created_at":    c.created_at,
            "tenant_id":     c.tenant_id,
        })
    return result


@router.post("/", response_model=ClusterOut)
async def create_cluster(body: ClusterCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await resolve_tenant(user, db)
    # Ensure the openstack cloud secret exists in the namespace before creating the cluster
    if tenant.clouds_yaml:
        capi.ensure_cloud_secret(tenant.namespace, tenant.os_cloud, tenant.clouds_yaml)
    params = {
        "cluster_name":   body.name,
        "namespace":      tenant.namespace,
        "k8s_version":    body.k8s_version,
        "cp_flavor":      body.cp_flavor,
        "worker_flavor":  body.worker_flavor,
        "worker_count":   body.worker_count,
        "os_cloud":             tenant.os_cloud,
        "external_network_id":  tenant.external_network_id,
    }
    capi.create_cluster(tenant.namespace, params)

    # Schedule background post-install (CCM + Cinder CSI) once the cluster is ready
    if tenant.clouds_yaml:
        tenant_info = TenantInfo(
            namespace=tenant.namespace,
            os_cloud=tenant.os_cloud,
            external_network_id=tenant.external_network_id or "",
            clouds_yaml=tenant.clouds_yaml,
        )
        schedule_post_install(body.name, tenant_info)

    c = Cluster(
        name=body.name, tenant_id=tenant.id, k8s_version=body.k8s_version,
        cp_flavor=body.cp_flavor, worker_flavor=body.worker_flavor,
        worker_count=body.worker_count, status="Provisioning"
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    await log_action(db, user.id, "create", f"cluster/{body.name}",
                     f"version={body.k8s_version} workers={body.worker_count}")
    return c


@router.delete("/{name}")
async def delete_cluster(name: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await resolve_tenant(user, db)
    capi.delete_cluster(tenant.namespace, name)
    from sqlalchemy import delete as sq_delete
    await db.execute(sq_delete(Cluster).where(Cluster.name == name, Cluster.tenant_id == tenant.id))
    await db.commit()
    await log_action(db, user.id, "delete", f"cluster/{name}", "")
    return {"deleted": name}


@router.get("/{name}/machines")
async def machines(name: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await resolve_tenant(user, db)
    return capi.list_machines(tenant.namespace, name)


@router.get("/{name}/kubeconfig", response_class=PlainTextResponse)
async def kubeconfig(name: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await resolve_tenant(user, db)
    return capi.get_kubeconfig(tenant.namespace, name)


@router.get("/{name}/events")
async def cluster_events(name: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await resolve_tenant(user, db)
    return capi.get_cluster_events(tenant.namespace, name)


@router.get("/{name}/workload-events")
async def workload_events(
    name: str,
    since: int = 60,
    limit: int = 200,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    tenant = await resolve_tenant(user, db)
    return capi.get_workload_events(tenant.namespace, name, since_minutes=since, limit=limit)


@router.get("/{name}/namespaces")
async def workload_namespaces(name: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await resolve_tenant(user, db)
    return capi.get_workload_namespaces(tenant.namespace, name)


@router.get("/{name}/resources")
async def workload_resources(
    name: str,
    ns: str = "default",
    kind: str = "pods",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    tenant = await resolve_tenant(user, db)
    return capi.get_workload_resources(tenant.namespace, name, ns, kind)


@router.get("/{name}/pod-logs")
async def pod_logs(
    name: str,
    ns: str,
    pod: str,
    container: str = "",
    lines: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from fastapi.responses import PlainTextResponse
    tenant = await resolve_tenant(user, db)
    logs = capi.get_pod_logs(tenant.namespace, name, ns, pod, container, lines)
    return PlainTextResponse(logs)


@router.patch("/{name}/scale")
async def scale_cluster(name: str, body: ScaleRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await resolve_tenant(user, db)
    capi.scale_workers(tenant.namespace, name, body.worker_count)
    from sqlalchemy import update
    await db.execute(
        update(Cluster).where(Cluster.name == name, Cluster.tenant_id == tenant.id)
        .values(worker_count=body.worker_count)
    )
    await db.commit()
    await log_action(db, user.id, "scale", f"cluster/{name}", f"worker_count={body.worker_count}")
    return {"scaled": name, "worker_count": body.worker_count}


@router.get("/{name}/readiness")
async def cluster_readiness(name: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return readiness status of the workload cluster for storage testing."""
    import subprocess, tempfile, os
    from kubernetes.client.exceptions import ApiException as K8sApiException

    tenant = await resolve_tenant(user, db)
    kubectl = os.environ.get("KUBECTL_PATH", "/usr/local/bin/kubectl")

    checks = {
        "kubeconfig":    {"ok": False, "label": "Kubeconfig disponible"},
        "nodes_ready":   {"ok": False, "label": "Nœuds Ready"},
        "storageclass":  {"ok": False, "label": "StorageClass cinder"},
        "csi_running":   {"ok": False, "label": "Pod Cinder CSI Running"},
    }

    try:
        kubeconfig_str = capi.get_kubeconfig(tenant.namespace, name)
        checks["kubeconfig"]["ok"] = True
    except Exception:
        return {"ready": False, "checks": checks}

    kf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    kf.write(kubeconfig_str)
    kf.close()
    kp = kf.name

    try:
        # Nodes ready?
        r = subprocess.run(
            [kubectl, "--kubeconfig", kp, "get", "nodes",
             "-o", "jsonpath={.items[*].status.conditions[-1].status}",
             "--request-timeout=8s"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            statuses = r.stdout.strip().split()
            checks["nodes_ready"]["ok"] = bool(statuses) and all(s == "True" for s in statuses)

        # StorageClass cinder?
        r = subprocess.run(
            [kubectl, "--kubeconfig", kp, "get", "storageclass", "cinder",
             "--ignore-not-found", "-o", "name", "--request-timeout=8s"],
            capture_output=True, text=True, timeout=10,
        )
        checks["storageclass"]["ok"] = bool(r.stdout.strip())

        # Cinder CSI pod Running?
        r = subprocess.run(
            [kubectl, "--kubeconfig", kp, "get", "pods", "-n", "kube-system",
             "-l", "app=csi-cinder-controllerplugin",
             "-o", "jsonpath={.items[0].status.phase}",
             "--request-timeout=8s"],
            capture_output=True, text=True, timeout=10,
        )
        checks["csi_running"]["ok"] = r.stdout.strip() == "Running"

    except Exception:
        pass
    finally:
        os.unlink(kp)

    ready = all(c["ok"] for c in checks.values())
    return {"ready": ready, "checks": checks}


@router.post("/{name}/test-storage")
async def test_storage(name: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Create a 1Gi test PVC on the workload cluster, verify it binds, then delete it."""
    import subprocess, tempfile, os, time
    from kubernetes.client.exceptions import ApiException as K8sApiException

    tenant = await resolve_tenant(user, db)

    # Check kubeconfig exists (cluster must be provisioned)
    try:
        kubeconfig_str = capi.get_kubeconfig(tenant.namespace, name)
    except K8sApiException as e:
        if e.status == 404:
            raise HTTPException(409, "Kubeconfig non disponible — le cluster n'est pas encore prêt")
        raise

    kf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    kf.write(kubeconfig_str)
    kf.close()
    kp = kf.name
    kubectl = os.environ.get("KUBECTL_PATH", "/usr/local/bin/kubectl")

    # Temporary StorageClass with Immediate binding so the PVC binds without a Pod
    sc_yaml = """apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: capi-platform-test-sc
provisioner: cinder.csi.openstack.org
allowVolumeExpansion: true
reclaimPolicy: Delete
volumeBindingMode: Immediate
"""
    pvc_yaml = """apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: capi-platform-storage-test
  namespace: default
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: capi-platform-test-sc
  resources:
    requests:
      storage: 1Gi
"""
    try:
        # 1. Verify API server connectivity
        ping = subprocess.run(
            [kubectl, "--kubeconfig", kp, "get", "nodes", "--request-timeout=10s"],
            capture_output=True, text=True, timeout=15,
        )
        if ping.returncode != 0:
            err = ping.stderr.strip()
            if "no route to host" in err or "connection refused" in err or "timeout" in err.lower():
                raise HTTPException(409, "API server inaccessible — le control plane démarre encore")
            raise HTTPException(500, f"Connexion cluster échouée: {err}")

        # 2. Check StorageClass 'cinder' exists
        sc_check = subprocess.run(
            [kubectl, "--kubeconfig", kp, "get", "storageclass", "cinder",
             "--ignore-not-found", "-o", "name"],
            capture_output=True, text=True, timeout=15,
        )
        if not sc_check.stdout.strip():
            raise HTTPException(409, "StorageClass 'cinder' absente — Cinder CSI pas encore installé sur ce cluster")

        # 3. Check Cinder CSI controller pod is Running
        csi_check = subprocess.run(
            [kubectl, "--kubeconfig", kp, "get", "pods", "-n", "kube-system",
             "-l", "app=csi-cinder-controllerplugin",
             "-o", "jsonpath={.items[0].status.phase}"],
            capture_output=True, text=True, timeout=15,
        )
        csi_phase = csi_check.stdout.strip()
        if csi_phase != "Running":
            raise HTTPException(409, f"Pod Cinder CSI non prêt (phase: {csi_phase or 'absent'}) — patientez quelques minutes")

        # 4. Create temp StorageClass (Immediate binding) + PVC
        subprocess.run(
            [kubectl, "--kubeconfig", kp, "apply", "-f", "-"],
            input=sc_yaml, text=True, capture_output=True, timeout=30,
        )
        r = subprocess.run(
            [kubectl, "--kubeconfig", kp, "apply", "-f", "-"],
            input=pvc_yaml, text=True, capture_output=True, timeout=30,
        )
        if r.returncode != 0:
            raise HTTPException(500, f"Création PVC échouée: {r.stderr.strip()}")

        # 5. Poll for Bound (max 60s)
        status = "Pending"
        for _ in range(12):
            time.sleep(5)
            r = subprocess.run(
                [kubectl, "--kubeconfig", kp, "get", "pvc",
                 "capi-platform-storage-test", "-n", "default",
                 "-o", "jsonpath={.status.phase}"],
                capture_output=True, text=True, timeout=15,
            )
            status = r.stdout.strip() or "Pending"
            if status == "Bound":
                break

        if status != "Bound":
            raise HTTPException(409, f"PVC non lié après 60s (statut: {status}) — vérifiez Cinder dans OpenStack")

        return {"status": "Bound", "size": "1Gi", "storageClass": "cinder", "message": "Cinder CSI fonctionnel"}

    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Timeout — le cluster ne répond pas")
    finally:
        # Patch PVC to remove finalizers before delete so CSI detaches cleanly
        subprocess.run(
            [kubectl, "--kubeconfig", kp, "patch", "pvc",
             "capi-platform-storage-test", "-n", "default",
             "-p", '{"metadata":{"finalizers":[]}}',
             "--type=merge", "--ignore-not-found"],
            capture_output=True, timeout=15,
        )
        time.sleep(2)
        subprocess.run(
            [kubectl, "--kubeconfig", kp,
             "delete", "pvc", "capi-platform-storage-test", "-n", "default",
             "--ignore-not-found", "--wait=false"],
            capture_output=True, timeout=30,
        )
        subprocess.run(
            [kubectl, "--kubeconfig", kp,
             "delete", "storageclass", "capi-platform-test-sc",
             "--ignore-not-found"],
            capture_output=True, timeout=30,
        )
        os.unlink(kp)


@router.patch("/{name}/upgrade")
async def upgrade_cluster(name: str, body: UpgradeRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant = await resolve_tenant(user, db)
    capi.upgrade_cluster(tenant.namespace, name, body.k8s_version)
    from sqlalchemy import update
    await db.execute(
        update(Cluster).where(Cluster.name == name, Cluster.tenant_id == tenant.id)
        .values(k8s_version=body.k8s_version)
    )
    await db.commit()
    await log_action(db, user.id, "upgrade", f"cluster/{name}", f"k8s_version={body.k8s_version}")
    return {"upgraded": name, "k8s_version": body.k8s_version}
