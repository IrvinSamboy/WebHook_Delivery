from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_session_factory(database_url: str) -> sessionmaker[Session]:
    # pool_pre_ping descarta conexiones muertas, por ejemplo tras reiniciar Postgres.
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(engine)
