from settings.settings import settings

settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_MODELS = [
    "app.node.models",
    "app.recordings.models",
]

# Local node state (SQLite): upload queue, segment index, cached assignments.
# This is the node's own small database, not the central PostgreSQL.
TORTOISE_ORM = {
    "connections": {"default": f"sqlite://{settings.db_path.as_posix()}"},
    "apps": {
        "models": {
            "models": [*APP_MODELS, "aerich.models"],
            "default_connection": "default",
        },
    },
    "use_tz": True,
    "timezone": "UTC",
}
