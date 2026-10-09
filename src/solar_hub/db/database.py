from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from solar_hub.core.config import Settings
from solar_hub.db.models import Base


def get_engine(database_url: str):
    """Cria a engine do SQLAlchemy garantindo a criação de diretórios para SQLite."""
    if database_url.startswith("sqlite:///"):
        file_path = Path(database_url.replace("sqlite:///", ""))
        file_path.parent.mkdir(parents=True, exist_ok=True)
    
    return create_engine(
        database_url,
        echo=False,
        connect_args={"check_same_thread": False} if "sqlite" in database_url else {}
    )


def init_db(database_url: str) -> None:
    """Cria todas as tabelas caso não existam."""
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    """Retorna a fábrica de sessões do SQLAlchemy."""
    engine = get_engine(database_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
