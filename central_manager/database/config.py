from settings.settings import settings

APP_MODELS = [
    "app.cameras.models",
    "app.nodes.models",
    "app.assignments.models",
    "app.recordings.models",
]

# Used by both the application and Aerich (`aerich init -t database.config.TORTOISE_ORM`).
TORTOISE_ORM = {
    "connections": {"default": settings.db_url},
    "apps": {
        "models": {
            "models": [*APP_MODELS, "aerich.models"],
            "default_connection": "default",
        },
    },
    "use_tz": True,
    "timezone": "UTC",
}
