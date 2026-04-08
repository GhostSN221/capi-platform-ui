from pydantic import BaseModel

class TenantCreate(BaseModel):
    name: str
    namespace: str
    os_cloud: str

class TenantOut(BaseModel):
    id: int
    name: str
    namespace: str
    os_cloud: str
    model_config = {"from_attributes": True}
