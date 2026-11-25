"""Los tests unitarios no necesitan un .env.

Algunos módulos leen la configuración al importarse (celery_app usa REDIS_URL
como broker). Estos valores ficticios solo se ponen si la variable no existe:
nunca se conecta nada a ellos, los tests usan fakes.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unit:unit@localhost:5432/unit")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
