# -*- coding: utf-8 -*-
"""Job service primitives for future background workers."""

from feedgrab.service.models import ProgressEvent


class JobService:
    """Create progress events without imposing a queue implementation yet."""

    def progress(self, stage: str, message: str, **kwargs) -> ProgressEvent:
        return ProgressEvent(stage=stage, message=message, **kwargs)
