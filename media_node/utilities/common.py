import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

logger = logging.getLogger("node")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_periodic(name: str, interval: float, func: Callable[[], Awaitable[None]]) -> None:
    """Run `func` forever every `interval` seconds; errors are logged, never fatal."""
    logger.info("Background loop '%s' started (every %ss)", name, interval)
    while True:
        try:
            await func()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background loop '%s' failed", name)
        await asyncio.sleep(interval)
