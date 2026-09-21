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
