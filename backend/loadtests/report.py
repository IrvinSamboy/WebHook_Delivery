"""Latencia de extremo a extremo de la última prueba de carga.

    make load-report

Para cada mensaje de la última aplicación "loadtest": desde que la API lo
aceptó (messages.created_at) hasta que el receptor respondió 2xx (inicio del
intento + su duración). Se calcula con lo que ya se guarda; no hace falta
instrumentar nada. Ambos relojes son de la misma máquina.
"""

from sqlalchemy import create_engine, text

from relay.config import get_settings

QUERY = text(
    """
    WITH app AS (
        SELECT id FROM applications WHERE name = 'loadtest'
        ORDER BY created_at DESC LIMIT 1
    ),
    msgs AS (
        SELECT m.id, m.created_at FROM messages m JOIN app ON m.app_id = app.id
    ),
    delivered AS (
        SELECT msgs.created_at AS accepted_at,
               a.started_at + a.duration_ms * interval '1 millisecond' AS delivered_at
        FROM msgs
        JOIN deliveries d ON d.message_id = msgs.id
        JOIN attempts a ON a.delivery_id = d.id
        WHERE a.response_status BETWEEN 200 AND 299
    ),
    lat AS (
        SELECT extract(epoch FROM delivered_at - accepted_at) * 1000 AS ms FROM delivered
    )
    SELECT
        (SELECT count(*) FROM msgs) AS messages,
        (SELECT count(*) FROM delivered) AS delivered,
        (SELECT extract(epoch FROM max(created_at) - min(created_at)) FROM msgs) AS accept_window,
        (SELECT extract(epoch FROM max(delivered_at) - min(accepted_at)) FROM delivered)
            AS delivery_window,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY ms) AS p50,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY ms) AS p95,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY ms) AS p99,
        max(ms) AS max
    FROM lat
    """
)


def main() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        row = connection.execute(QUERY).mappings().one()
    if not row["messages"]:
        print("No hay mensajes de una aplicación 'loadtest': ejecuta antes make load.")
        return

    pending = row["messages"] - row["delivered"]
    print(f"Mensajes aceptados: {row['messages']} en {row['accept_window'] or 0:.0f} s")
    print(f"Entregados (2xx):   {row['delivered']}  · pendientes: {pending}")
    if row["delivered"]:
        rate = row["delivered"] / max(float(row["delivery_window"]), 1)
        print(f"Ritmo de entrega:   {rate:.1f} webhooks/s")
        print("Latencia de extremo a extremo (aceptado → entregado):")
        for name in ("p50", "p95", "p99", "max"):
            print(f"  {name:>4}: {row[name]:8.0f} ms")


if __name__ == "__main__":
    main()
