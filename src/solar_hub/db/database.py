from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from solar_hub.db.models import Base


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Configurações essenciais para ambientes com concorrência (ex: thread daemon + requisições web):
    - journal_mode=WAL (Write-Ahead Logging) permite leituras e escritas simultâneas sem bloqueio.
    - busy_timeout=5000 aguarda até 5 segundos antes de lançar 'database is locked'.
    - synchronous=NORMAL melhora o throughput de I/O em disco com segurança de integridade.
    """
    # Verifica se a conexão é SQLite
    if type(dbapi_connection).__module__.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
        except Exception:
            pass
        finally:
            cursor.close()


@lru_cache(maxsize=4)
def get_engine(database_url: str):
    """
    Cria ou reutiliza uma engine singleton do SQLAlchemy com pool de conexões ativo.
    Evita o anti-padrão de recriar engines e pools a cada requisição HTTP.
    """
    if database_url.startswith("sqlite:///"):
        file_path = Path(database_url.replace("sqlite:///", ""))
        file_path.parent.mkdir(parents=True, exist_ok=True)

    return create_engine(
        database_url,
        echo=False,
        connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
    )


def init_db(database_url: str) -> None:
    """Cria todas as tabelas caso não existam (executar apenas na inicialização)."""
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)


@lru_cache(maxsize=4)
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    """Retorna a fábrica de sessões do SQLAlchemy com engine reaproveitada."""
    engine = get_engine(database_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
