from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://capi:capi@postgres:5432/capidb"
    redis_url:    str = "redis://redis:6379"
    secret_key:   str = "change-me-in-production"
    algorithm:    str = "HS256"
    token_expire: int = 480

    # --- Réseau des clusters créés -------------------------------------------
    # 100.64.0.0/16 (CGNAT) : ne chevauche ni l'on-prem 192.168.x
    # (DB 192.168.120.x, Nutanix 192.168.10.x) ni le réseau des nœuds.
    pod_cidr:     str = "100.64.0.0/16"
    service_cidr: str = "10.96.0.0/12"

    # CNI Calico : VXLAN (encapsulé), PAS IPIP.
    # Sur OpenStack le port security (anti-spoofing) interdit le routage direct
    # des IP de pods : CrossSubnet casse le pod->pod (testé sur datacloud-platform).
    calico_ipip_mode:  str = "Never"
    calico_vxlan_mode: str = "Always"

    # MTU des pods. "0" = auto (Calico calcule : MTU underlay - 50 en VXLAN).
    # Underlay OpenStack 1450 -> 1400.
    calico_mtu: str = "0"

    class Config:
        env_file = ".env"

settings = Settings()
