"""API errors with readable messages (port of nvr_client/src/api/client.ts::errorMessage)."""

import httpx


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None, detail=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.detail = detail

    def __str__(self) -> str:
        return self.message


def error_message(response: httpx.Response) -> str:
    """FastAPI errors: {"detail": "text"} or {"detail": [{"loc": [...], "msg": ...}, ...]}."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or f"Request failed (HTTP {response.status_code})")
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            loc = ".".join(str(x) for x in (item.get("loc") or [])[1:])
            parts.append(f"{loc}: {item.get('msg', '')}" if loc else str(item.get("msg", "")))
        return "; ".join(parts)
    return f"Request failed (HTTP {response.status_code})"


def raise_for_response(response: httpx.Response) -> None:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        code = detail.get("code") if isinstance(detail, dict) else None
        raise ApiError(response.status_code, error_message(response), code=code, detail=detail)
