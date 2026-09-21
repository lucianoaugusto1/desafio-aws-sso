# Plano 1 — Aplicação SSO (API + front, sem AWS)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o microserviço de autenticação e o front estático que o consome, rodando e testáveis inteiramente na máquina local, sem nenhuma credencial AWS.

**Architecture:** FastAPI com SQLAlchemy 2.0 sobre PostgreSQL. Configuração vem de variáveis de ambiente; em produção um módulo separado hidrata essas variáveis a partir do Secrets Manager antes do app subir, o que mantém o resto do código sem qualquer dependência de AWS. Front é HTML e JavaScript puro, sem build, lendo o endereço da API de um `config.js` gerado.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, psycopg 3, PyJWT, bcrypt, pytest, Docker Compose.

**Escopo deste plano:** Fase 2 do spec, mais o código do front da Fase 4.
**Fora de escopo:** templates CloudFormation, scripts de ciclo de vida e workflows — vão para o Plano 2.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `api/requirements.txt` | Dependências de execução |
| `api/requirements-dev.txt` | Dependências de teste e lint |
| `api/pyproject.toml` | Configuração de ruff e pytest (sem empacotamento) |
| `api/app/settings.py` | Configuração tipada lida do ambiente |
| `api/app/models.py` | Tabela `users` |
| `api/app/db.py` | Engine, sessionmaker e a dependência `get_session` |
| `api/app/security.py` | Hash de senha e emissão/validação de JWT |
| `api/app/schemas.py` | Contratos de entrada e saída da API |
| `api/app/aws_secrets.py` | Hidrata o ambiente a partir do Secrets Manager |
| `api/app/main.py` | Aplicação FastAPI e as 4 rotas |
| `api/tests/conftest.py` | Cliente de teste com SQLite em memória |
| `api/tests/test_*.py` | Testes por unidade |
| `api/Dockerfile` | Imagem da API |
| `api/docker-compose.yml` | Postgres + API para desenvolvimento local |
| `web/index.html` | Formulários de cadastro, login e sessão |
| `web/app.js` | Chamadas à API e persistência do token |
| `web/config.example.js` | Modelo do `config.js` que o pipeline gera |

O corte é por responsabilidade, não por camada: `security.py` não sabe o que é uma requisição HTTP, `db.py` não sabe o que é um usuário, e `aws_secrets.py` é a única porção do código que conhece a AWS.

---

### Task 1: Esqueleto do projeto Python

**Files:**
- Create: `api/requirements.txt`, `api/requirements-dev.txt`, `api/pyproject.toml`
- Delete: `api/app/.gitkeep`, `api/tests/.gitkeep`

- [ ] **Step 1: Criar o arquivo de dependências de execução**

`api/requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
sqlalchemy==2.0.36
psycopg[binary]==3.2.3
pydantic[email]==2.10.4
pydantic-settings==2.7.0
bcrypt==4.2.1
pyjwt==2.10.1
boto3==1.35.90
```

- [ ] **Step 2: Criar o arquivo de dependências de desenvolvimento**

`api/requirements-dev.txt`:

```
-r requirements.txt
pytest==8.3.4
httpx==0.28.1
ruff==0.8.6
```

- [ ] **Step 3: Configurar ruff e pytest**

`api/pyproject.toml` — este arquivo configura ferramentas, não empacota nada. `pythonpath = ["."]` é o que permite `from app.settings import ...` funcionar nos testes sem instalar o projeto.

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 4: Criar o ambiente virtual e instalar**

Run:
```bash
cd api && python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt && .venv/bin/python -c "import fastapi, sqlalchemy, jwt, bcrypt; print('ok')"
```
Expected: imprime `ok`

- [ ] **Step 5: Remover os placeholders e commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
rm -f api/app/.gitkeep api/tests/.gitkeep
git add api/requirements.txt api/requirements-dev.txt api/pyproject.toml
git add -u
git commit -m "chore(api): dependências e configuração de ruff e pytest"
```

---

### Task 2: Configuração tipada

**Files:**
- Create: `api/app/settings.py`
- Test: `api/tests/test_settings.py`

- [ ] **Step 1: Escrever o teste que falha**

`api/tests/test_settings.py`:

```python
from app.settings import get_settings


def test_le_configuracao_do_ambiente(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("JWT_SECRET", "segredo-de-teste")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert settings.jwt_secret == "segredo-de-teste"
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expires_seconds == 3600


def test_configuracao_e_cacheada(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "primeiro")
    get_settings.cache_clear()
    primeiro = get_settings()

    monkeypatch.setenv("JWT_SECRET", "segundo")
    segundo = get_settings()

    assert primeiro is segundo
    assert segundo.jwt_secret == "primeiro"
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_settings.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implementar**

`api/app/settings.py`:

```python
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
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd api && .venv/bin/pytest tests/test_settings.py -v`
Expected: 2 passed

- [ ] **Step 5: Commitar**

```bash
git add api/app/settings.py api/tests/test_settings.py
git commit -m "feat(api): configuração tipada lida do ambiente"
```

---

### Task 3: Modelo de dados e sessão

**Files:**
- Create: `api/app/models.py`, `api/app/db.py`
- Test: `api/tests/test_models.py`

- [ ] **Step 1: Escrever o teste que falha**

`api/tests/test_models.py`:

```python
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Base, User


def test_persiste_e_recupera_usuario():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        session.add(User(email="ana@exemplo.com", password_hash="hash-falso"))
        session.commit()

    with Session() as session:
        user = session.scalar(select(User).where(User.email == "ana@exemplo.com"))

    assert user is not None
    assert user.id == 1
    assert user.email == "ana@exemplo.com"
    assert user.created_at is not None


def test_email_e_unico():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add(User(email="ana@exemplo.com", password_hash="a"))
        session.commit()
        session.add(User(email="ana@exemplo.com", password_hash="b"))
        with pytest.raises(IntegrityError):
            session.commit()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_models.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Implementar o modelo**

`api/app/models.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 4: Implementar a camada de sessão**

`api/app/db.py` — o engine é criado sob demanda e memoizado. Isso importa: no container, `app.aws_secrets` precisa escrever `DATABASE_URL` no ambiente **antes** do primeiro acesso ao banco, e criar o engine na importação do módulo quebraria isso.

```python
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão por requisição."""
    with get_sessionmaker()() as session:
        yield session
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `cd api && .venv/bin/pytest tests/test_models.py -v`
Expected: 2 passed

- [ ] **Step 6: Commitar**

```bash
git add api/app/models.py api/app/db.py api/tests/test_models.py
git commit -m "feat(api): tabela users e camada de sessão do SQLAlchemy"
```

---

### Task 4: Hash de senha e JWT

**Files:**
- Create: `api/app/security.py`
- Test: `api/tests/test_security.py`

- [ ] **Step 1: Escrever o teste que falha**

`api/tests/test_security.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_security.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.security'`

- [ ] **Step 3: Implementar**

`api/app/security.py`:

```python
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.settings import get_settings


def hash_password(password: str) -> str:
    """bcrypt trunca em 72 bytes; o limite é imposto no schema de entrada."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(subject: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_expires_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Levanta jwt.PyJWTError (assinatura inválida, expirado, malformado)."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd api && .venv/bin/pytest tests/test_security.py -v`
Expected: 5 passed

- [ ] **Step 5: Commitar**

```bash
git add api/app/security.py api/tests/test_security.py
git commit -m "feat(api): hash bcrypt de senha e emissão de JWT"
```

---

### Task 5: Contratos de entrada e saída

**Files:**
- Create: `api/app/schemas.py`
- Test: `api/tests/test_schemas.py`

- [ ] **Step 1: Escrever o teste que falha**

`api/tests/test_schemas.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_schemas.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.schemas'`

- [ ] **Step 3: Implementar**

`api/app/schemas.py` — o teto de 72 caracteres na senha não é capricho: acima disso o bcrypt levanta erro, então validar aqui transforma um 500 em um 422 com mensagem clara.

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd api && .venv/bin/pytest tests/test_schemas.py -v`
Expected: 5 passed

- [ ] **Step 5: Commitar**

```bash
git add api/app/schemas.py api/tests/test_schemas.py
git commit -m "feat(api): schemas de credenciais, usuário e token"
```

---

### Task 6: Aplicação FastAPI e a rota de health

**Files:**
- Create: `api/app/main.py`, `api/tests/conftest.py`
- Test: `api/tests/test_health.py`

- [ ] **Step 1: Escrever o conftest**

`api/tests/conftest.py` — `TestClient(app)` é construído **sem** `with`, de propósito: assim o lifespan não roda, e nenhum teste tenta abrir conexão com PostgreSQL.

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base
from app.settings import get_settings


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "segredo-de-teste")
    monkeypatch.setenv("JWT_EXPIRES_SECONDS", "3600")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    """Cliente HTTP com a sessão apontando para SQLite em memória.

    StaticPool mantém a mesma conexão entre chamadas — sem isso cada sessão
    abriria um banco em memória novo e vazio.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _session_de_teste():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_session] = _session_de_teste
    yield TestClient(app)
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Escrever o teste que falha**

`api/tests/test_health.py`:

```python
def test_health_reporta_banco_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
```

- [ ] **Step 3: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_health.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 4: Implementar**

`api/app/main.py` — o `lifespan` é o único lugar que hidrata segredos e cria tabelas, e ele só roda quando o servidor sobe de verdade. `app.aws_secrets` ainda não existe; será criado na Task 10.

```python
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_engine, get_session
from app.models import Base


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=get_engine())
    yield


app = FastAPI(title="SSO Lab", version="0.1.0", lifespan=lifespan)

# Laboratório: o front vem de outra origem (website do S3) e não há domínio
# fixo, então qualquer origem é aceita. Em produção isto seria uma lista.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    """Prova que a task alcança o banco — é a verificação da Fase 3."""
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"banco indisponível: {exc.__class__.__name__}",
        ) from exc
    return {"status": "ok", "db": "ok"}
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `cd api && .venv/bin/pytest tests/test_health.py -v`
Expected: 1 passed

- [ ] **Step 6: Commitar**

```bash
git add api/app/main.py api/tests/conftest.py api/tests/test_health.py
git commit -m "feat(api): aplicação FastAPI com rota de health"
```

---

### Task 7: Cadastro de usuário

**Files:**
- Modify: `api/app/main.py`
- Test: `api/tests/test_register.py`

- [ ] **Step 1: Escrever o teste que falha**

`api/tests/test_register.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_register.py -v`
Expected: FAIL — todos os 3 retornam 404, porque a rota não existe

- [ ] **Step 3: Implementar**

Acrescentar os imports ao topo de `api/app/main.py`:

```python
from sqlalchemy import select, text

from app.models import Base, User
from app.schemas import Credentials, UserOut
from app.security import hash_password
```

E a rota ao final de `api/app/main.py`:

```python
@app.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(body: Credentials, session: Session = Depends(get_session)) -> User:
    if session.scalar(select(User).where(User.email == body.email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="e-mail já cadastrado",
        )

    user = User(email=body.email, password_hash=hash_password(body.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd api && .venv/bin/pytest tests/test_register.py -v`
Expected: 3 passed

- [ ] **Step 5: Commitar**

```bash
git add api/app/main.py api/tests/test_register.py
git commit -m "feat(api): rota POST /auth/register"
```

---

### Task 8: Login

**Files:**
- Modify: `api/app/main.py`
- Test: `api/tests/test_login.py`

- [ ] **Step 1: Escrever o teste que falha**

`api/tests/test_login.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_login.py -v`
Expected: FAIL — os 3 retornam 404

- [ ] **Step 3: Implementar**

Ampliar os imports em `api/app/main.py`:

```python
from app.schemas import Credentials, Token, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.settings import get_settings
```

E acrescentar a rota. As duas falhas devolvem a **mesma** mensagem de propósito: responder "usuário não existe" entregaria a um atacante a lista de e-mails cadastrados.

```python
@app.post("/auth/login", response_model=Token)
def login(body: Credentials, session: Session = Depends(get_session)) -> Token:
    user = session.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="credenciais inválidas",
        )

    return Token(
        access_token=create_access_token(str(user.id)),
        expires_in=get_settings().jwt_expires_seconds,
    )
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd api && .venv/bin/pytest tests/test_login.py -v`
Expected: 3 passed

- [ ] **Step 5: Commitar**

```bash
git add api/app/main.py api/tests/test_login.py
git commit -m "feat(api): rota POST /auth/login com emissão de JWT"
```

---

### Task 9: Sessão corrente

**Files:**
- Modify: `api/app/main.py`
- Test: `api/tests/test_me.py`

- [ ] **Step 1: Escrever o teste que falha**

`api/tests/test_me.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_me.py -v`
Expected: FAIL — os 4 retornam 404

- [ ] **Step 3: Implementar**

Ampliar os imports em `api/app/main.py`:

```python
import jwt
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
```

Declarar o esquema logo após o `add_middleware`. `auto_error=False` faz o FastAPI devolver `None` em vez de um 403 automático, o que nos deixa responder 401 com mensagem própria:

```python
bearer_scheme = HTTPBearer(auto_error=False)
```

E acrescentar a rota:

```python
@app.get("/auth/me", response_model=UserOut)
def me(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token ausente",
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token inválido",
        ) from exc

    user = session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="usuário não encontrado",
        )
    return user
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd api && .venv/bin/pytest tests/test_me.py -v`
Expected: 4 passed

- [ ] **Step 5: Rodar a suíte inteira e o lint**

Run: `cd api && .venv/bin/pytest -q && .venv/bin/ruff check .`
Expected: 25 passed, e ruff sem apontamentos

- [ ] **Step 6: Commitar**

```bash
git add api/app/main.py api/tests/test_me.py
git commit -m "feat(api): rota GET /auth/me com validação de bearer token"
```

---

### Task 10: Leitura dos segredos da AWS

**Files:**
- Create: `api/app/aws_secrets.py`
- Modify: `api/app/main.py`
- Test: `api/tests/test_aws_secrets.py`

- [ ] **Step 1: Escrever o teste que falha**

`api/tests/test_aws_secrets.py` — o teste injeta um cliente falso, então nenhuma credencial AWS é necessária e nenhuma chamada de rede acontece.

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd api && .venv/bin/pytest tests/test_aws_secrets.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.aws_secrets'`

- [ ] **Step 3: Implementar**

`api/app/aws_secrets.py` — este é o único módulo do projeto que conhece a AWS. Host, porta e nome do banco vêm por variável de ambiente (a TaskDefinition os preenche a partir dos Outputs do CloudFormation), e não do segredo: o segredo gerenciado pelo RDS garante apenas `username` e `password`.

```python
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
```

- [ ] **Step 4: Ligar ao ciclo de vida da aplicação**

Em `api/app/main.py`, acrescentar o import:

```python
from app.aws_secrets import hydrate_env_from_secrets
```

E substituir a função `lifespan` inteira por esta. A ordem importa: hidratar, invalidar o cache da configuração, só então tocar no banco.

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    hydrate_env_from_secrets()
    get_settings.cache_clear()
    Base.metadata.create_all(bind=get_engine())
    yield
```

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `cd api && .venv/bin/pytest -q`
Expected: 29 passed

- [ ] **Step 6: Commitar**

```bash
git add api/app/aws_secrets.py api/app/main.py api/tests/test_aws_secrets.py
git commit -m "feat(api): hidratação do ambiente a partir do Secrets Manager"
```

---

### Task 11: Empacotamento e verificação ponta a ponta local

**Files:**
- Create: `api/Dockerfile`, `api/.dockerignore`, `api/docker-compose.yml`

- [ ] **Step 1: Escrever o Dockerfile**

`api/Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Escrever o .dockerignore**

`api/.dockerignore`:

```
.venv/
tests/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
requirements-dev.txt
```

- [ ] **Step 3: Escrever o compose de desenvolvimento**

`api/docker-compose.yml` — o `healthcheck` do Postgres com `depends_on: condition` evita a corrida clássica em que a API sobe antes do banco aceitar conexões.

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: sso
      POSTGRES_PASSWORD: sso
      POSTGRES_DB: sso
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sso"]
      interval: 3s
      timeout: 3s
      retries: 10

  api:
    build: .
    environment:
      DATABASE_URL: postgresql+psycopg://sso:sso@db:5432/sso
      JWT_SECRET: dev-secret-nao-use-em-producao
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
```

- [ ] **Step 4: Subir e verificar o fluxo completo**

Run (o daemon do Docker precisa estar rodando):
```bash
cd api && docker compose up -d --build && sleep 12
curl -s localhost:8000/health
curl -s -X POST localhost:8000/auth/register -H 'content-type: application/json' \
  -d '{"email":"ana@exemplo.com","password":"senha-segura"}'
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"email":"ana@exemplo.com","password":"senha-segura"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"
```
Expected, nesta ordem:
```
{"status":"ok","db":"ok"}
{"id":1,"email":"ana@exemplo.com","created_at":"..."}
{"id":1,"email":"ana@exemplo.com","created_at":"..."}
```

- [ ] **Step 5: Derrubar e commitar**

```bash
cd api && docker compose down -v
cd /Users/lucianobr01/desafio-aws-sso
git add api/Dockerfile api/.dockerignore api/docker-compose.yml
git commit -m "feat(api): imagem Docker e compose de desenvolvimento"
```

---

### Task 12: Front estático

**Files:**
- Create: `web/index.html`, `web/app.js`, `web/config.example.js`
- Delete: `web/.gitkeep`

- [ ] **Step 1: Escrever o modelo de configuração**

`web/config.example.js` — o `config.js` real não é versionado; `scripts/up.sh` e o workflow de deploy o geram com o IP da task do momento.

```javascript
// Copie para config.js ao desenvolver local.
// Em produção este arquivo é gerado a cada deploy com o IP público da task.
window.API_URL = "http://localhost:8000";
```

- [ ] **Step 2: Escrever a página**

`web/index.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SSO Lab</title>
  <style>
    :root { color-scheme: light dark; }
    body {
      font-family: system-ui, sans-serif;
      max-width: 28rem;
      margin: 3rem auto;
      padding: 0 1rem;
      line-height: 1.5;
    }
    fieldset { border: 1px solid currentColor; border-radius: .5rem; margin-bottom: 1.5rem; }
    label { display: block; margin-bottom: .75rem; }
    input { width: 100%; padding: .5rem; box-sizing: border-box; }
    button { padding: .5rem 1rem; margin-right: .5rem; cursor: pointer; }
    #saida { padding: .75rem; border-radius: .5rem; background: rgba(127,127,127,.15); white-space: pre-wrap; }
  </style>
</head>
<body>
  <h1>SSO Lab</h1>
  <p>Laboratório de infraestrutura AWS. Sem HTTPS, dados descartáveis.</p>

  <fieldset>
    <legend>Credenciais</legend>
    <label>E-mail <input id="email" type="email" value="ana@exemplo.com"></label>
    <label>Senha <input id="senha" type="password" value="senha-segura"></label>
    <button id="btn-cadastrar">Cadastrar</button>
    <button id="btn-entrar">Entrar</button>
  </fieldset>

  <fieldset>
    <legend>Sessão</legend>
    <button id="btn-quem-sou">Quem sou eu</button>
    <button id="btn-sair">Sair</button>
  </fieldset>

  <div id="saida">Pronto.</div>

  <script src="config.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Escrever o JavaScript**

`web/app.js`:

```javascript
const saida = document.getElementById("saida");

function mostrar(titulo, dados) {
  saida.textContent = `${titulo}\n${JSON.stringify(dados, null, 2)}`;
}

function credenciais() {
  return {
    email: document.getElementById("email").value,
    password: document.getElementById("senha").value,
  };
}

async function chamar(rota, opcoes = {}) {
  const resposta = await fetch(`${window.API_URL}${rota}`, opcoes);
  return { status: resposta.status, corpo: await resposta.json() };
}

document.getElementById("btn-cadastrar").onclick = async () => {
  const { status, corpo } = await chamar("/auth/register", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(credenciais()),
  });
  mostrar(`Cadastro — HTTP ${status}`, corpo);
};

document.getElementById("btn-entrar").onclick = async () => {
  const { status, corpo } = await chamar("/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(credenciais()),
  });
  if (corpo.access_token) {
    localStorage.setItem("token", corpo.access_token);
  }
  mostrar(`Login — HTTP ${status}`, corpo);
};

document.getElementById("btn-quem-sou").onclick = async () => {
  const token = localStorage.getItem("token");
  const { status, corpo } = await chamar("/auth/me", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  mostrar(`Sessão — HTTP ${status}`, corpo);
};

document.getElementById("btn-sair").onclick = () => {
  localStorage.removeItem("token");
  saida.textContent = "Token removido do navegador.";
};
```

- [ ] **Step 4: Verificar no navegador contra a API local**

Run:
```bash
cd /Users/lucianobr01/desafio-aws-sso
cp web/config.example.js web/config.js
(cd api && docker compose up -d --build) && sleep 12
(cd web && python3 -m http.server 5500 &) && sleep 2
open http://localhost:5500
```
Expected: clicar em **Cadastrar** mostra `HTTP 201` com o id do usuário; **Entrar** mostra `HTTP 200` com um `access_token`; **Quem sou eu** mostra `HTTP 200` com o e-mail. Clicar em **Cadastrar** de novo mostra `HTTP 409`.

- [ ] **Step 5: Encerrar e commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
pkill -f "http.server 5500"
(cd api && docker compose down -v)
rm -f web/.gitkeep
git add web/index.html web/app.js web/config.example.js
git add -u
git commit -m "feat(web): front estático de cadastro, login e sessão"
```

---

## Verificação final do plano

- [ ] `cd api && .venv/bin/pytest -q` → 29 passed
- [ ] `cd api && .venv/bin/ruff check .` → sem apontamentos
- [ ] `docker compose up` seguido dos 4 `curl` da Task 11 → as 3 respostas esperadas
- [ ] Front no navegador executa cadastro, login e sessão contra a API local
- [ ] `git log --oneline` → 12 commits, um por task

Ao fim deste plano existe software funcionando e testado, sem nenhuma dependência de conta AWS. O Plano 2 pega esta imagem e este front e os coloca no ar.
