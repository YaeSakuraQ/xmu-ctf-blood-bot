"""NoneBot/OneBot notifier.

Messages are sent as a single ``text`` segment, never as a concatenated CQ
string. That keeps a team name containing ``[CQ:...]`` from being interpreted
as a mention or an image.
"""

from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from ctfblood.notifier import Notifier


class NoneBotNotifier(Notifier):
    def __init__(self, group_id: int, *, dry_run: bool = False) -> None:
        self.group_id = group_id
        self.dry_run = dry_run

    async def send(self, text: str) -> None:
        if self.dry_run:
            logger.info("[DRY-RUN] group {}:\n{}", self.group_id, text)
            return
        bot = nonebot.get_bot()
        await bot.send_group_msg(
            group_id=self.group_id,
            message=Message([MessageSegment.text(text)]),
        )

    async def send_admin(self, text: str) -> None:
        if self.dry_run:
            logger.warning("[DRY-RUN] admin:\n{}", text)
            return
        bot = nonebot.get_bot()
        for user_id in nonebot.get_driver().config.superusers:
            try:
                await bot.send_private_msg(
                    user_id=int(user_id),
                    message=Message([MessageSegment.text(text)]),
                )
            except Exception as exc:  # noqa: BLE001 - one admin may not have added the bot
                logger.warning("给管理员 {} 发送私聊失败: {}", user_id, exc)
