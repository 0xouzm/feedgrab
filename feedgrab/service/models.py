# -*- coding: utf-8 -*-
"""Stable data models for the feedgrab service layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from feedgrab.schema import UnifiedContent


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "app_secret",
    "appmsg_token",
    "auth_token",
    "cookie",
    "ct0",
    "key",
    "next_auth",
    "pass_ticket",
    "secret",
    "session",
    "token",
)


def _redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, value in data.items():
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            redacted[key] = "[redacted]"
        elif isinstance(value, dict):
            redacted[key] = _redact_mapping(value)
        else:
            redacted[key] = value
    return redacted


@dataclass
class Artifact:
    """A file or external artifact produced by a service operation."""

    kind: str
    path: str
    content_type: str = "text/markdown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "content_type": self.content_type,
            "metadata": dict(self.metadata),
        }


@dataclass
class FetchRequest:
    """Input for fetching one URL."""

    url: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "metadata": dict(self.metadata),
        }


@dataclass
class FetchResult:
    """Structured output for one fetch operation."""

    request: FetchRequest
    content: Optional[UnifiedContent] = None
    artifacts: list[Artifact] = field(default_factory=list)
    platform: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "content": self.content.to_dict() if self.content else None,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "platform": self.platform,
            "fetched_at": self.fetched_at,
        }


@dataclass
class ProgressEvent:
    """Progress signal emitted by future GUI/MCP workers."""

    stage: str
    message: str
    url: str = ""
    platform: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "message": self.message,
            "url": self.url,
            "platform": self.platform,
            "details": _redact_mapping(dict(self.details)),
            "created_at": self.created_at,
        }


class ServiceError(Exception):
    """Service-layer exception with JSON-safe context."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "service_error",
        recoverable: bool = True,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.recoverable = recoverable
        self.details = _redact_mapping(dict(details or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "details": dict(self.details),
        }


@dataclass
class DiagnosticResult:
    """One diagnostic check result."""

    name: str
    status: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": _redact_mapping(dict(self.details)),
        }
