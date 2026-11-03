"""Platform error model: {code, message, field_errors, related}."""

from __future__ import annotations

from dataclasses import dataclass, field

STATUS = {
    "NOT_FOUND": 404,
    "VALIDATION": 422,
    "INVALID_TRANSITION": 409,
    "CONFLICT": 409,
    "MODEL_UNAVAILABLE": 503,
    "REPO_DIRTY": 409,
    "RUN_ACTIVE": 409,
    "AUTH_REQUIRED": 401,
    "FORBIDDEN_ORIGIN": 403,
    "FORBIDDEN": 403,
    "CSRF_FAILED": 403,
    "PASSWORD_CHANGE_REQUIRED": 403,
    "LOGIN_FAILED": 401,
    "RATE_LIMITED": 429,
    "DB_UNAVAILABLE": 503,
    "CONFIG_MISSING": 500,
    "ARTIFACT_CORRUPT": 500,
    "ARTIFACT_TOO_LARGE": 413,
    "INSTANCE_LOCKED": 409,
    "MIGRATION_MISMATCH": 500,
    "UPSTREAM": 502,
    "ENV_UNREACHABLE": 503,
}


@dataclass
class AppError(Exception):
    code: str
    message: str
    field_errors: list[dict] = field(default_factory=list)
    related: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.code not in STATUS:
            raise ValueError(f"unknown error code {self.code}")
        super().__init__(self.message)

    @property
    def status(self) -> int:
        return STATUS[self.code]

    def body(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "field_errors": self.field_errors,
            "related": self.related,
        }
