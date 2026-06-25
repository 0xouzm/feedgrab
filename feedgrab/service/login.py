# -*- coding: utf-8 -*-
"""Login service wrappers for existing browser/session login flows."""

from feedgrab.login import login


class LoginService:
    """Run the existing platform login flow."""

    def login(self, platform: str, headless: bool = False) -> None:
        login(platform, headless=headless)
