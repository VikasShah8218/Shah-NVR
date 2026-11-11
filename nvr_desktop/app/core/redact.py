"""Hide sign-in tokens in anything that is logged or shown (docs/DESKTOP_AUTH_PLAN.md §6)."""

import re

_TOKEN_RE = re.compile(r"(access_token=)[^&\s#]+")


def redact(text: str) -> str:
    return _TOKEN_RE.sub(r"\g<1>***", text)
