import pytest
from pydantic import ValidationError

from app.schemas import Credentials, Token


def test_aceita_credenciais_validas():
    creds = Credentials(email="ana@exemplo.com", password="senha-segura")

    assert creds.email == "ana@exemplo.com"


def test_rejeita_email_malformado():
    with pytest.raises(ValidationError):
        Credentials(email="nao-e-email", password="senha-segura")


def test_rejeita_senha_curta():
    with pytest.raises(ValidationError):
        Credentials(email="ana@exemplo.com", password="curta")


def test_rejeita_senha_acima_do_limite_do_bcrypt():
    with pytest.raises(ValidationError):
        Credentials(email="ana@exemplo.com", password="a" * 73)


def test_token_tem_tipo_bearer_por_padrao():
    token = Token(access_token="abc", expires_in=3600)

    assert token.token_type == "bearer"
