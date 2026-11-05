from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from relay.config import get_settings
from relay.infrastructure.db.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

engine = create_engine(get_settings().database_url)

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
