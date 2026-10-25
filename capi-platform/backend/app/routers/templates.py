from fastapi import APIRouter
router = APIRouter()

K8S_VERSIONS = ["v1.31.6", "v1.30.13", "v1.29.15", "v1.34.3"]
FLAVORS = [
    {"name": "k8s.master.small",  "vcpus": 2,  "ram": 4096,  "disk": 20},
    {"name": "k8s.master.medium", "vcpus": 4,  "ram": 8192,  "disk": 50},
    {"name": "k8s.master.large",  "vcpus": 8,  "ram": 16384, "disk": 100},
    {"name": "k8s.node.small",    "vcpus": 2,  "ram": 4096,  "disk": 40},
    {"name": "k8s.node.medium",   "vcpus": 4,  "ram": 8192,  "disk": 80},
    {"name": "k8s.node.large",    "vcpus": 8,  "ram": 16384, "disk": 100},
    {"name": "k8s.node.xlarge",   "vcpus": 16, "ram": 32768, "disk": 200},
]

@router.get("/k8s-versions")
def k8s_versions():
    return K8S_VERSIONS

@router.get("/flavors")
def flavors():
    return FLAVORS
