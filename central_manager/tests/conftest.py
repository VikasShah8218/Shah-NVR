"""Never let application-lifespan tests connect to the developer's configured database."""
import os

# Set before test modules import settings/database.config/main.
os.environ["DATABASE_URL"] = "sqlite://:memory:"
# Tests start with auth off, whatever the developer's .env says; auth tests switch it on themselves.
os.environ["AUTH_ENABLED"] = "false"
