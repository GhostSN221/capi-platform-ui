from pydantic import BaseModel
from datetime import datetime


class ClusterTemplateCreate(BaseModel):
    name: str
    k8s_version: str
    cp_flavor: str
    worker_flavor: str
    worker_count: int = 3
    description: str = ""


class ClusterTemplateOut(BaseModel):
    id: int
    name: str
    k8s_version: str
    cp_flavor: str
    worker_flavor: str
    worker_count: int
    description: str
    created_by: int | None
    created_at: datetime
    model_config = {"from_attributes": True}
