"""Chat commands for status, live rank, blood table, test and reload."""

from __future__ import annotations

import nonebot
from nonebot import on_command
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg

from ctfblood.detector import blood_table
from ctfblood.messages import format_blood_table, format_event, format_rank
from ctfblood.models import BloodEvent

from . import get_service, get_settings, reload_service

HELP = (
    "【CTF 血报】\n"
    "/ctf status — 运行状态\n"
    "/ctf rank [N] — 实时前 N 名（默认 10）\n"
    "/ctf blood [关键词] — 当前血况（可按题目/方向过滤）\n"
    "/ctf test — 发一条测试消息（管理员）\n"
    "/ctf reload — 重载 .env 配置（管理员）"
)


async def _allowed(event: MessageEvent) -> bool:
    if event.message_type == "private":
        return True
    return event.group_id == get_settings().group_id


def _is_superuser(event: MessageEvent) -> bool:
    return event.get_user_id() in nonebot.get_driver().config.superusers


ctf = on_command("ctf", rule=_allowed, priority=5, block=True)


@ctf.handle()
async def _handle(event: MessageEvent, arg: Message = CommandArg()) -> None:
    service = get_service()
    parts = arg.extract_plain_text().strip().split()
    sub = parts[0].lower() if parts else "status"

    if sub in {"help", "?"}:
        await ctf.finish(HELP)

    if sub == "status":
        await ctf.finish(service.status_text(bot_ready=bool(nonebot.get_bots())))

    if sub == "rank":
        limit = 10
        if len(parts) > 1 and parts[1].isdigit():
            limit = max(1, min(int(parts[1]), 50))
        try:
            snapshot = await service.client.fetch_snapshot()
        except Exception as exc:  # noqa: BLE001 - reply instead of crashing the handler
            logger.warning("拉取榜单失败: {}", exc)
            await ctf.finish(f"拉取榜单失败：{exc}")
        await ctf.finish(format_rank(snapshot, limit))

    if sub == "blood":
        keyword = parts[1].lower() if len(parts) > 1 else ""
        try:
            snapshot = await service.client.fetch_snapshot()
        except Exception as exc:  # noqa: BLE001
            logger.warning("拉取血况失败: {}", exc)
            await ctf.finish(f"拉取血况失败：{exc}")
        table = blood_table(snapshot)
        if keyword:
            table = [
                (challenge, winners)
                for challenge, winners in table
                if keyword in challenge.name.lower() or keyword in challenge.direction.lower()
            ]
        if not table:
            await ctf.finish("没有匹配的血。" if keyword else "当前还没有任何血。")
        await ctf.finish(format_blood_table(table, limit=15))

    if sub == "test":
        if not _is_superuser(event):
            await ctf.finish("仅管理员可用。")
        sample = BloodEvent(
            race_id=get_settings().race_id,
            challenge_id="test",
            challenge_name="测试题目",
            direction="Web",
            blood=1,
            team_id="test-team",
            team_name="测试队伍",
            solve_time=None,
            score=105,
            time_exact=False,
        )
        try:
            await service.notifier.send(format_event(sample))
        except Exception as exc:  # noqa: BLE001
            await ctf.finish(f"测试消息发送失败：{exc}")
        await ctf.finish("已发送测试消息。")

    if sub == "reload":
        if not _is_superuser(event):
            await ctf.finish("仅管理员可用。")
        try:
            message = await reload_service()
        except Exception as exc:  # noqa: BLE001
            logger.exception("重载失败: {}", exc)
            await ctf.finish(f"重载失败：{exc}")
        await ctf.finish(message)

    await ctf.finish(HELP)
