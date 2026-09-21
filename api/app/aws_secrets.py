import json
import os
from typing import Any
from urllib.parse import quote_plus


def _client() -> Any:
    import boto3

    return boto3.client(
        "secretsmanager",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


def _ler(client: Any, arn: str) -> dict[str, Any]:
    return json.loads(client.get_secret_value(SecretId=arn)["SecretString"])


def hydrate_env_from_secrets(client: Any = None) -> None:
    """Escreve DATABASE_URL e JWT_SECRET no ambiente a partir do Secrets Manager.

    Sem os ARNs no ambiente a função não faz nada — é isso que permite rodar
    local com docker compose sem nenhuma credencial AWS.
    """
    db_arn = os.getenv("DB_SECRET_ARN")
    jwt_arn = os.getenv("JWT_SECRET_ARN")
    if not db_arn and not jwt_arn:
        return

    client = client or _client()

    if db_arn:
        segredo = _ler(client, db_arn)
        usuario = quote_plus(segredo["username"])
        senha = quote_plus(segredo["password"])
        host = os.environ["DB_HOST"]
        porta = os.environ["DB_PORT"]
        nome = os.environ["DB_NAME"]
        os.environ["DATABASE_URL"] = (
            f"postgresql+psycopg://{usuario}:{senha}@{host}:{porta}/{nome}"
        )

    if jwt_arn:
        os.environ["JWT_SECRET"] = _ler(client, jwt_arn)["jwt_secret"]
