"""Las migraciones se aplican y se deshacen, y coinciden con los modelos."""

from alembic import command
from sqlalchemy import inspect

from conftest import alembic_config


def test_las_migraciones_coinciden_con_los_modelos(test_database_url):
    # Falla si un modelo cambió y falta la migración correspondiente.
    command.check(alembic_config())


def test_se_pueden_deshacer_y_volver_a_aplicar(engine):
    config = alembic_config()

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}

    command.upgrade(config, "head")
    assert {"applications", "endpoints", "messages", "deliveries", "attempts"} <= set(
        inspect(engine).get_table_names()
    )
