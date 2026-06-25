# -*- coding: utf-8 -*-
"""Settings service exposing path/config helpers without duplicating logic."""

from feedgrab.config import get_cookie_dir, get_data_dir, get_session_dir, get_user_agent


class SettingsService:
    """Read core feedgrab runtime settings."""

    def data_dir(self):
        return get_data_dir()

    def cookie_dir(self):
        return get_cookie_dir()

    def session_dir(self):
        return get_session_dir()

    def user_agent(self) -> str:
        return get_user_agent()
