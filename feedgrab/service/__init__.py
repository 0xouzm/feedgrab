# -*- coding: utf-8 -*-
"""Structured service API for feedgrab clients.

The first-stage service layer is intentionally thin: it wraps the existing
reader/storage/login/config behavior so CLI and MCP can share one backend
contract without changing platform fetcher semantics.
"""

from feedgrab.service.fetch import FetchService
from feedgrab.service.models import (
    Artifact,
    DiagnosticResult,
    FetchRequest,
    FetchResult,
    ProgressEvent,
    ServiceError,
)

__all__ = [
    "Artifact",
    "DiagnosticResult",
    "FetchRequest",
    "FetchResult",
    "FetchService",
    "ProgressEvent",
    "ServiceError",
]
