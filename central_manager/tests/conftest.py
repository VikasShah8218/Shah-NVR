"""Never let application-lifespan tests connect to the developer's configured database."""
import os

# Set before test modules import settings/database.config/main.
os.environ["DATABASE_URL"] = "sqlite://:memory:"
