"""Pure blood-detection logic.

This module has no I/O and no NoneBot dependency, which makes it easy to test
with recorded or synthetic scoreboards.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from .models import Candidate, Challenge, Snapshot, Team

logger = logging.getLogger(__name__)


def find_candidates(
    snapshot: Snapshot,
    announced: Iterable[tuple[str, int]],
    levels: Iterable[int] = (1, 2, 3),
) -> list[Candidate]:
    """Return bloods present in ``snapshot`` that are not in ``announced``.

    ``announced`` contains ``(challenge_id, blood_level)`` keys. The platform's
    ``rank`` field is the 1-based solve order *per challenge* and is only
    populated when ``reward_mode == 1``; for other modes the function returns
    an empty list instead of mislabelling every solve as a first blood.
    """

    if snapshot.reward_mode != 1:
        return []

    allowed = set(levels)
    done = set(announced)
    candidates: list[Candidate] = []
    seen: set[tuple[str, int]] = set()

    challenge_count = len(snapshot.challenges)
    teams = [team for team in snapshot.teams if len(team.cells) == challenge_count]
    if len(teams) != len(snapshot.teams):
        logger.warning(
            "有 %d 支队伍的 checker_score 长度与题目数不一致，已跳过",
            len(snapshot.teams) - len(teams),
        )

    for index, challenge in enumerate(snapshot.challenges):
        for team in teams:
            cell = team.cells[index]
            if not cell.is_solved or cell.rank not in allowed:
                continue
            key = (challenge.challenge_id, cell.rank)
            if key in done or key in seen:
                continue
            seen.add(key)
            candidates.append(Candidate(challenge=challenge, blood=cell.rank, team=team))

    candidates.sort(key=lambda item: (item.blood, item.challenge.name))
    return candidates


def blood_table(
    snapshot: Snapshot,
    levels: Iterable[int] = (1, 2, 3),
) -> list[tuple[Challenge, list[tuple[int, Team]]]]:
    """Build a ``challenge -> [(blood, team), ...]`` view for chat commands."""

    allowed = set(levels)
    challenge_count = len(snapshot.challenges)
    teams = [team for team in snapshot.teams if len(team.cells) == challenge_count]
    table: list[tuple[Challenge, list[tuple[int, Team]]]] = []
    for index, challenge in enumerate(snapshot.challenges):
        winners: list[tuple[int, Team]] = []
        for team in teams:
            cell = team.cells[index]
            if cell.is_solved and cell.rank in allowed:
                winners.append((cell.rank, team))
        winners.sort(key=lambda item: item[0])
        if winners:
            table.append((challenge, winners))
    return table


def validate_snapshot(snapshot: Snapshot) -> list[str]:
    """Return human-readable warnings; used by the startup self-check."""

    warnings: list[str] = []
    if snapshot.reward_mode != 1:
        warnings.append(
            f"reward_mode={snapshot.reward_mode}，平台未启用一/二/三血加成，机器人不会播报血序"
        )
    if not snapshot.challenges:
        warnings.append("榜单没有题目（checker_detail 为空）")
    if not snapshot.teams:
        warnings.append("榜单没有队伍（rank_detail 为空）")
    for index, team in enumerate(snapshot.teams):
        if len(team.cells) != len(snapshot.challenges):
            warnings.append(
                f"第 {index + 1} 支队伍 {team.name!r} 的 checker_score 长度不一致"
            )
            break
    return warnings
