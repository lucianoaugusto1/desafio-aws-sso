from datetime import UTC, datetime, timedelta

import jwt

CREDENCIAIS = {"email": "ana@exemplo.com", "password": "senha-segura"}


def _token(client) -> str:
    client.post("/auth/register", json=CREDENCIAIS)
    return client.post("/auth/login", json=CREDENCIAIS).json()["access_token"]


def test_devolve_o_usuario_do_token(client):
    token = _token(client)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "ana@exemplo.com"
    assert body["id"] == 1


def test_rejeita_requisicao_sem_token(client):
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "token ausente"


def test_rejeita_token_com_assinatura_invalida(client):
    falso = jwt.encode({"sub": "1"}, "outra-chave", algorithm="HS256")

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {falso}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "token inválido"


def test_rejeita_token_de_usuario_removido(client):
    orfao = jwt.encode(
        {"sub": "999", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "segredo-de-teste",
        algorithm="HS256",
    )

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {orfao}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "usuário não encontrado"
