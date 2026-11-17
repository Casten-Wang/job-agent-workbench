"""HTTP input validation; node outputs and evidence need separate validation."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StartInterview(StrictModel):
    material_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    mode: Literal["resume_readiness", "mock_interview"] = "resume_readiness"
    target: dict[str, str] = Field(default_factory=dict)

    @field_validator("target")
    @classmethod
    def valid_target(cls, value):
        if any(k not in {"company", "role", "round"} or len(v) > 200 for k, v in value.items()):
            raise ValueError("Invalid target fields")
        return value


class Turn(StrictModel):
    event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    text: str = Field(min_length=1, max_length=12000)
    command: Literal["request_hint", "open_book", "ai_assisted", "skip", "pause", "resume", "finish", "retry", "correct_contribution", "correct_version"] | None = None

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Empty input")
        return value
