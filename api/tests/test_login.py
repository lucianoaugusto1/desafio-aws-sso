from app.security import decode_access_token

CREDENCIAIS = {"email": "ana@exemplo.com", "password": "senha-segura"}


def test_login_devolve_token_utilizavel(client):
    client.post("/auth/register", json=CREDENCIAIS)

    response = client.post("/auth/login", json=CREDENCIAIS)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert decode_access_token(body["access_token"])["sub"] == "1"


def test_rejeita_senha_errada(client):
    client.post("/auth/register", json=CREDENCIAIS)

    response = client.post(
        "/auth/login",
        json={"email": "ana@exemplo.com", "password": "senha-errada"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "credenciais inválidas"


def test_rejeita_usuario_inexistente(client):
    response = client.post(
        "/auth/login",
        json={"email": "ninguem@exemplo.com", "password": "senha-segura"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "credenciais inválidas"
