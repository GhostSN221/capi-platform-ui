import os
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
import yaml, base64
from kubernetes import client as k8s_client
from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth import get_current_user

router = APIRouter()

def _load_preconfigured_clouds_yaml() -> bytes | None:
    path = os.getenv("OS_CLOUDS_YAML")
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None

@router.post("/")
async def setup(
    namespace: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.tenant_id:
        raise HTTPException(400, "Already configured")

    content = _load_preconfigured_clouds_yaml()
    if not content:
        raise HTTPException(500, "clouds.yaml non trouvé sur le serveur (OS_CLOUDS_YAML non défini)")

    external_network_id = os.getenv("OS_EXTERNAL_NETWORK_ID", "")
    if not external_network_id:
        raise HTTPException(500, "OS_EXTERNAL_NETWORK_ID non défini")

    try:
        clouds_data = yaml.safe_load(content)
        clouds = clouds_data.get("clouds", {})
        if not clouds:
            raise ValueError()
        os_cloud = list(clouds.keys())[0]
    except Exception:
        raise HTTPException(500, "clouds.yaml invalide")

    core = k8s_client.CoreV1Api()

    try:
        core.create_namespace(k8s_client.V1Namespace(
            metadata=k8s_client.V1ObjectMeta(name=namespace)
        ))
    except Exception:
        pass

    secret_name = f"{os_cloud}-cloud-config"
    try:
        core.create_namespaced_secret(namespace, k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(name=secret_name, namespace=namespace),
            data={
                "clouds.yaml": base64.b64encode(content).decode(),
                "cacert": "",
            },
        ))
    except Exception:
        pass

    tenant = Tenant(
        name=user.username,
        namespace=namespace,
        os_cloud=os_cloud,
        external_network_id=external_network_id,
        clouds_yaml=content.decode(errors="replace"),
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    await db.execute(update(User).where(User.id == user.id).values(tenant_id=tenant.id))
    await db.commit()

    return {"status": "ok", "os_cloud": os_cloud, "namespace": namespace}
