"""add listing indexes

CONCURRENTLY: el índice se construye sin bloquear las escrituras, así la API
sigue aceptando mensajes aunque la tabla sea grande. No puede ir dentro de una
transacción, de ahí el autocommit_block.

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            'ix_deliveries_endpoint_id_created_at', 'deliveries', ['endpoint_id', 'created_at'],
            unique=False, postgresql_concurrently=True, if_not_exists=True,
        )
        op.create_index(
            'ix_messages_app_id_created_at_id', 'messages', ['app_id', 'created_at', 'id'],
            unique=False, postgresql_concurrently=True, if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            'ix_messages_app_id_created_at_id', table_name='messages',
            postgresql_concurrently=True, if_exists=True,
        )
        op.drop_index(
            'ix_deliveries_endpoint_id_created_at', table_name='deliveries',
            postgresql_concurrently=True, if_exists=True,
        )
