import jwt
import pytest

from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.settings import get_settings


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "segredo-de-teste")
    monkeypatch.setenv("JWT_EXPIRES_SECONDS", "3600")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_hash_nao_e_a_senha_e_verifica():
    hashed = hash_password("senha-correta")

    assert hashed != "senha-correta"
    assert verify_password("senha-correta", hashed) is True
    assert verify_password("senha-errada", hashed) is False


def test_hashes_da_mesma_senha_sao_diferentes():
    assert hash_password("mesma-senha") != hash_password("mesma-senha")


def test_token_carrega_o_subject():
    token = create_access_token("42")

    payload = decode_access_token(token)

    assert payload["sub"] == "42"
    assert payload["exp"] > payload["iat"]


def test_token_assinado_com_outra_chave_e_rejeitado():
    token = jwt.encode({"sub": "42"}, "outra-chave", algorithm="HS256")

    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token)


def test_token_expirado_e_rejeitado(monkeypatch):
    monkeypatch.setenv("JWT_EXPIRES_SECONDS", "-10")
    get_settings.cache_clear()
    token = create_access_token("42")

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)
