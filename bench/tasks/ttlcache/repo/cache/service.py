"""Looks up user profiles from a slow backend."""

from typing import Callable


class ProfileService:
    def __init__(self, backend: Callable[[str], dict]):
        self.backend = backend

    def profile(self, user_id: str) -> dict:
        return self.backend(user_id)
