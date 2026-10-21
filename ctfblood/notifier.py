"""Notifier interface used by the service (no NoneBot import here)."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send(self, text: str) -> None: ...

    async def send_admin(self, text: str) -> None: ...


class DryRunNotifier:
    """Print messages instead of sending them to QQ."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)
        logger.info("[DRY-RUN] group message:\n%s", text)
        print(f"----- DRY-RUN GROUP -----\n{text}\n-------------------------")

    async def send_admin(self, text: str) -> None:
        logger.warning("[DRY-RUN] admin message: %s", text)
        print(f"----- DRY-RUN ADMIN -----\n{text}\n-------------------------")
