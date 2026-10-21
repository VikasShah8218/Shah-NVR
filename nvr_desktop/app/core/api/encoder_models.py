"""Credential-free H2 responses, independent of the server's Python package."""
from app.core.api.models import ApiModel


class EncoderState(ApiModel):
    api: str
    profile_token: str | None
    encoder_token: str | None = None
    revision: str | None = None
    current: dict | None = None
    options: list[dict] = []
    profiles: list[dict] = []
    shared_profiles: list[str] = []
    use_count: int = 0
    warnings: list[str] = []


class EncoderChange(ApiModel):
    id: str
    status: str
    created_at: str
    before: EncoderState | None = None
    result: dict | None = None


class EncoderHistory(ApiModel):
    changes: list[EncoderChange] = []
    pending: EncoderChange | None = None
