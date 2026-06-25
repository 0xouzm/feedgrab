# -*- coding: utf-8 -*-
"""Small diagnostic service primitives."""

from feedgrab.service.models import DiagnosticResult


class DoctorService:
    """Collect structured diagnostic results for future non-CLI clients."""

    def check_import(self, module_name: str, label: str = "") -> DiagnosticResult:
        name = label or module_name
        try:
            __import__(module_name)
            return DiagnosticResult(name=name, status="ok", message="available")
        except ImportError as exc:
            return DiagnosticResult(name=name, status="warning", message=str(exc))
