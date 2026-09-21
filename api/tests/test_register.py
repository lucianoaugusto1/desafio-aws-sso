def test_cadastra_usuario(client):
    response = client.post(
        "/auth/register",
        json={"email": "ana@exemplo.com", "password": "senha-segura"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ana@exemplo.com"
    assert body["id"] == 1
    assert "password" not in body
    assert "password_hash" not in body


def test_rejeita_email_ja_cadastrado(client):
    payload = {"email": "ana@exemplo.com", "password": "senha-segura"}
    client.post("/auth/register", json=payload)

    response = client.post("/auth/register", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "e-mail já cadastrado"


def test_rejeita_payload_invalido(client):
    response = client.post(
        "/auth/register",
        json={"email": "nao-e-email", "password": "x"},
    )

    assert response.status_code == 422
