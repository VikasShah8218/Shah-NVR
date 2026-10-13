"""API errors with readable messages (port of nvr_client/src/api/client.ts::errorMessage)."""

import httpx


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    def __str__(self) -> str:
        return self.message


def error_message(response: httpx.Response) -> str:
    """FastAPI errors: {"detail": "text"} or {"detail": [{"loc": [...], "msg": ...}, ...]}."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            loc = ".".join(str(x) for x in (item.get("loc") or [])[1:])
            parts.append(f"{loc}: {item.get('msg', '')}" if loc else str(item.get("msg", "")))
        return "; ".join(parts)
    return f"Request failed (HTTP {response.status_code})"


def raise_for_response(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise ApiError(response.status_code, error_message(response))
