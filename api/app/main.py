from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_engine, get_session
from app.models import Base, User
from app.schemas import Credentials, UserOut
from app.security import hash_password


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
