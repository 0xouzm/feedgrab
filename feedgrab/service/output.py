# -*- coding: utf-8 -*-
"""Output service wrappers for existing storage utilities."""

from feedgrab.schema import UnifiedContent
from feedgrab.utils.storage import save_to_markdown


class OutputService:
    """Persist normalized content using the legacy Markdown formatter."""

    def save_markdown(self, content: UnifiedContent, filepath: str = None):
        return save_to_markdown(content, filepath=filepath)
