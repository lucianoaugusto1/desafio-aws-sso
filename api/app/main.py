from contextlib import asynccontextmanager
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.aws_secrets import hydrate_env_from_secrets
from app.db import get_engine, get_session
from app.models import Base, User
from app.schemas import Credentials, Token, UserOut
from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    # A ordem importa: hidratar o ambiente, invalidar o cache da configuração,
    # só então tocar no banco — o engine é construído sob demanda.
    hydrate_env_from_secrets()
    get_settings.cache_clear()
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

# auto_error=False faz o FastAPI devolver None em vez de um 403 automático,
# o que nos deixa responder 401 com mensagem própria.
bearer_scheme = HTTPBearer(auto_error=False)

# Aliases de injeção: o FastAPI lê o Depends de dentro do Annotated, o que
# mantém as assinaturas legíveis e sem chamada de função no valor default.
SessionDep = Annotated[Session, Depends(get_session)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


@app.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    """Prova que a task alcança o banco — é a verificação da Fase 3."""
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"banco indisponível: {exc.__class__.__name__}",
        ) from exc
    return {"status": "ok", "db": "ok"}


@app.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(body: Credentials, session: SessionDep) -> User:
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


@app.post("/auth/login", response_model=Token)
def login(body: Credentials, session: SessionDep) -> Token:
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


@app.get("/auth/me", response_model=UserOut)
def me(credentials: CredentialsDep, session: SessionDep) -> User:
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
