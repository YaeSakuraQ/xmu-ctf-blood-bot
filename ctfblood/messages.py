"""Plain-text message formatting.

Messages are sent as OneBot *text segments* by the notifier, so team names are
data rather than CQ code. The helpers here still strip control characters and
cap length to keep a malicious team name from breaking the layout.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import BloodEvent, Challenge, Snapshot, Team

BLOOD_LABEL = {1: "一血", 2: "二血", 3: "三血"}
BLOOD_ICON = {1: "🏆", 2: "🩸", 3: "🩸"}

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_text(value: str, limit: int = 40) -> str:
    text = _CONTROL.sub("", str(value)).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text or "未知"


def _clock(value: str | None, exact: bool) -> str:
    if not value:
        return "时间未知"
    match = re.search(r"(\d{2}:\d{2}:\d{2})", value)
    if not match:
        return safe_text(value, 19)
    return match.group(1) if exact else f"约 {match.group(1)}"


def format_event(event: BloodEvent) -> str:
    label = BLOOD_LABEL.get(event.blood, f"第{event.blood}血")
    icon = BLOOD_ICON.get(event.blood, "🩸")
    suffix = "（补报）" if event.catchup else ""
    lines = [
        f"{icon} {label}{suffix}",
        f"{safe_text(event.direction, 20)} · {safe_text(event.challenge_name, 60)}",
        f"队伍：{safe_text(event.team_name)}",
        f"时间：{_clock(event.solve_time, event.time_exact)}",
    ]
    if event.score is not None and event.score > 0:
        lines.append(f"得分：{event.score}")
    return "\n".join(lines)


def format_digest(events: Iterable[BloodEvent]) -> str:
    """Compact multiple events into one message (used for catch-up bursts)."""

    items = list(events)
    if not items:
        return ""
    if len(items) == 1:
        return format_event(items[0])
    first = _clock(items[0].solve_time, items[0].time_exact)
    lines = [f"【血报 · {first}】"]
    for event in items:
        label = BLOOD_LABEL.get(event.blood, f"第{event.blood}血")
        line = (
            f"{BLOOD_ICON.get(event.blood, '🩸')} {label} "
            f"{safe_text(event.direction, 12)}/{safe_text(event.challenge_name, 30)} "
            f"— {safe_text(event.team_name, 30)}"
        )
        if event.score:
            line += f"（{event.score}）"
        lines.append(line)
    return "\n".join(lines)


def format_status(
    *,
    race_name: str,
    race_id: str,
    poll_interval: float,
    send_interval: float,
    counts: dict[str, int],
    last_poll: str | None,
    last_error: str | None,
    bot_ready: bool,
) -> str:
    lines = [
        "【CTF 播报状态】",
        f"赛事：{safe_text(race_name or '未获取', 60)}",
        f"ID：{race_id}",
        f"轮询：{poll_interval:g}s  发送：{send_interval:g}s",
        f"已发送：{counts.get('sent', 0)}  待发送：{counts.get('pending', 0)}  "
        f"失败：{counts.get('failed', 0)}",
        f"最近轮询：{last_poll or '尚未'}",
        f"Bot：{'已连接' if bot_ready else '未连接'}",
    ]
    if last_error:
        lines.append(f"最近错误：{safe_text(last_error, 120)}")
    return "\n".join(lines)


def format_rank(snapshot: Snapshot, limit: int = 10) -> str:
    teams = sorted(snapshot.teams, key=lambda team: (-team.score, -team.solved, team.name))
    lines = [f"【实时排名 · 前 {min(limit, len(teams))}】"]
    for position, team in enumerate(teams[:limit], start=1):
        lines.append(f"{position}. {safe_text(team.name, 30)}  {team.score} 分 / {team.solved} 题")
    if not teams:
        lines.append("暂无队伍数据")
    return "\n".join(lines)


def format_blood_table(
    table: list[tuple[Challenge, list[tuple[int, Team]]]],
    limit: int = 10,
) -> str:
    if not table:
        return "当前还没有任何血。"
    lines = ["【血况】"]
    for challenge, winners in table[:limit]:
        lines.append(f"{safe_text(challenge.direction, 12)} · {safe_text(challenge.name, 40)}")
        for blood, team in winners:
            lines.append(f"  {BLOOD_LABEL.get(blood, f'第{blood}血')} {safe_text(team.name, 30)}")
    return "\n".join(lines)
