from fastapi import APIRouter
router = APIRouter()

K8S_VERSIONS = ["v1.31.6", "v1.30.13"]
FLAVORS = ["m1.tiny", "k8s.master", "k8s.node", "sow-flavor"]

@router.get("/k8s-versions")
def k8s_versions():
    return K8S_VERSIONS

@router.get("/flavors")
def flavors():
    return FLAVORS
