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
