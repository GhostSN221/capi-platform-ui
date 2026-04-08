from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://capi:capi@postgres:5432/capidb"
    redis_url:    str = "redis://redis:6379"
    secret_key:   str = "change-me-in-production"
    algorithm:    str = "HS256"
    token_expire: int = 480

    class Config:
        env_file = ".env"

settings = Settings()
