from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração da aplicação, lida de variáveis de ambiente.

    Os defaults servem ao desenvolvimento local com docker compose. Em produção
    todos são sobrescritos: DATABASE_URL e JWT_SECRET por app.aws_secrets, e os
    demais pela TaskDefinition do ECS.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql+psycopg://sso:sso@localhost:5432/sso"
    jwt_secret: str = "dev-secret-nao-use-em-producao"
    jwt_algorithm: str = "HS256"
    jwt_expires_seconds: int = 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
