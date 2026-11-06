"""encrypt endpoint secret

Escrita a mano: autogenerate vería un renombrado como borrar la columna y crear
otra, y se perderían los secretos existentes.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Callable

from alembic import op
from cryptography.fernet import Fernet
import sqlalchemy as sa

from relay.config import get_settings

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _transform_column(column: str, transform: Callable[[bytes], bytes]) -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(f"SELECT id, {column} AS value FROM endpoints")).all()
    for row in rows:
        connection.execute(
            sa.text(f"UPDATE endpoints SET {column} = :value WHERE id = :id"),
            {"id": row.id, "value": transform(row.value.encode()).decode()},
        )


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.get_secret_value())


def upgrade() -> None:
    _transform_column("secret", _fernet().encrypt)
    op.alter_column("endpoints", "secret", new_column_name="secret_encrypted")


def downgrade() -> None:
    _transform_column("secret_encrypted", _fernet().decrypt)
    op.alter_column("endpoints", "secret_encrypted", new_column_name="secret")
