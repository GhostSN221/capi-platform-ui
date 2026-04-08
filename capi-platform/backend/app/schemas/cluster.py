import re
from pydantic import BaseModel, field_validator
from datetime import datetime

class ClusterCreate(BaseModel):
    name: str
    k8s_version: str
    cp_flavor: str
    worker_flavor: str
    worker_count: int = 3
    tenant_id: int | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Le nom du cluster est requis")
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', v):
            raise ValueError("Nom invalide : minuscules, chiffres et tirets uniquement")
        return v

class ClusterOut(BaseModel):
    id: int
    name: str
    k8s_version: str
    cp_flavor: str
    worker_flavor: str
    worker_count: int
    status: str
    namespace: str | None = None
    created_at: datetime
    tenant_id: int
    model_config = {"from_attributes": True}
