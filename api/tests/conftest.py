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
