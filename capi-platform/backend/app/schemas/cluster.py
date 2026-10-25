import re
from pydantic import BaseModel, field_validator
from datetime import datetime

class ClusterCreate(BaseModel):
    name: str
    k8s_version: str
    cp_flavor: str
    worker_flavor: str
    master_count: int = 1
    worker_count: int = 3
    node_cidr: str = "10.6.0.0/24"
    tenant_id: int | None = None

    @field_validator("node_cidr")
    @classmethod
    def validate_node_cidr(cls, v: str) -> str:
        import ipaddress
        try:
            ipaddress.IPv4Network(v, strict=False)
        except ValueError:
            raise ValueError("node_cidr doit être un CIDR IPv4 valide (ex: 10.7.0.0/24)")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Le nom du cluster est requis")
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', v):
            raise ValueError("Nom invalide : minuscules, chiffres et tirets uniquement")
        return v

    @field_validator("master_count")
    @classmethod
    def validate_master_count(cls, v: int) -> int:
        if v not in (1, 3, 5):
            raise ValueError("Le nombre de control planes doit être 1, 3 ou 5")
        return v

class ClusterOut(BaseModel):
    id: int
    name: str
    k8s_version: str
    cp_flavor: str
    worker_flavor: str
    master_count: int
    worker_count: int
    status: str
    namespace: str | None = None
    created_at: datetime
    tenant_id: int
    model_config = {"from_attributes": True}
