import logging
from collections import deque


class RingBufferHandler(logging.Handler):
    """Keeps the most recent formatted log lines in memory for the /api/v1/logs endpoint."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            self.handleError(record)

    def tail(self, n: int) -> list[str]:
        return list(self.lines)[-n:]


log_buffer = RingBufferHandler()
