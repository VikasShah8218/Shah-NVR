"""Shared user-visible product branding."""

from __future__ import annotations

import json
from pathlib import Path


DESKTOP_DIR = Path(__file__).resolve().parents[2]
BRANDING_FILE = DESKTOP_DIR / "branding.json"


def _load_branding() -> tuple[str, Path]:
    try:
        branding = json.loads(BRANDING_FILE.read_text(encoding="utf-8"))
        name = branding["productName"]
        logo = branding["logo"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot load product branding from {BRANDING_FILE}") from exc
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError(f"productName in {BRANDING_FILE} must be a non-empty string")
    if not isinstance(logo, str) or not logo.strip():
        raise RuntimeError(f"logo in {BRANDING_FILE} must be a non-empty relative path")

    logo_path = (DESKTOP_DIR / logo).resolve()
    if not logo_path.is_relative_to(DESKTOP_DIR) or not logo_path.is_file():
        raise RuntimeError(f"logo in {BRANDING_FILE} must reference a file inside {DESKTOP_DIR}")
    if logo_path.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".ico", ".webp"}:
        raise RuntimeError("Desktop logo must be SVG, PNG, JPG, JPEG, ICO, or WebP")
    return name.strip(), logo_path


PRODUCT_NAME, PRODUCT_LOGO_PATH = _load_branding()
