import json
import os

from app.aws_secrets import hydrate_env_from_secrets


class ClienteFalso:
    def __init__(self, segredos: dict[str, dict]):
        self._segredos = segredos
        self.chamadas: list[str] = []

    def get_secret_value(self, SecretId: str) -> dict[str, str]:  # noqa: N803
        self.chamadas.append(SecretId)
        return {"SecretString": json.dumps(self._segredos[SecretId])}


def test_nao_faz_nada_sem_arns(monkeypatch):
    monkeypatch.delenv("DB_SECRET_ARN", raising=False)
    monkeypatch.delenv("JWT_SECRET_ARN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://local")
    cliente = ClienteFalso({})

    hydrate_env_from_secrets(client=cliente)

    assert cliente.chamadas == []
    assert os.environ["DATABASE_URL"] == "postgresql+psycopg://local"


def test_monta_a_url_do_banco_a_partir_do_segredo(monkeypatch):
    monkeypatch.setenv("DB_SECRET_ARN", "arn:db")
    monkeypatch.delenv("JWT_SECRET_ARN", raising=False)
    monkeypatch.setenv("DB_HOST", "instancia.rds.amazonaws.com")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "sso")
    cliente = ClienteFalso({"arn:db": {"username": "postgres", "password": "abc123"}})

    hydrate_env_from_secrets(client=cliente)

    assert os.environ["DATABASE_URL"] == (
        "postgresql+psycopg://postgres:abc123@instancia.rds.amazonaws.com:5432/sso"
    )


def test_escapa_caracteres_especiais_da_senha(monkeypatch):
    monkeypatch.setenv("DB_SECRET_ARN", "arn:db")
    monkeypatch.delenv("JWT_SECRET_ARN", raising=False)
    monkeypatch.setenv("DB_HOST", "h")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "sso")
    cliente = ClienteFalso({"arn:db": {"username": "postgres", "password": "a/b@c:d"}})

    hydrate_env_from_secrets(client=cliente)

    assert "a%2Fb%40c%3Ad" in os.environ["DATABASE_URL"]


def test_le_a_chave_de_assinatura(monkeypatch):
    monkeypatch.delenv("DB_SECRET_ARN", raising=False)
    monkeypatch.setenv("JWT_SECRET_ARN", "arn:jwt")
    cliente = ClienteFalso({"arn:jwt": {"jwt_secret": "chave-de-producao"}})

    hydrate_env_from_secrets(client=cliente)

    assert os.environ["JWT_SECRET"] == "chave-de-producao"
