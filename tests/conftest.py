from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ctfblood.models import BloodEvent, Cell, Challenge, Snapshot, Team  # noqa: E402


def make_challenge(
    challenge_id: str = "c1",
    name: str = "easysql",
    direction: str = "Web",
    score: int = 100,
) -> Challenge:
    return Challenge(challenge_id=challenge_id, name=name, direction=direction, score=score)


def make_cell(rank: int = 0, solved: bool = False) -> Cell:
    return Cell(rank=rank, is_solved=solved)


def make_team(
    team_id: str = "t1",
    name: str = "A队",
    cells: tuple[Cell, ...] = (),
    score: int = 0,
    solved: int | None = None,
) -> Team:
    return Team(
        team_id=team_id,
        name=name,
        score=score,
        solved=sum(1 for cell in cells if cell.is_solved) if solved is None else solved,
        cells=cells,
    )


def make_snapshot(
    challenges: tuple[Challenge, ...] = (make_challenge(),),
    teams: tuple[Team, ...] = (),
    reward_mode: int = 1,
) -> Snapshot:
    return Snapshot(
        race_id="race",
        reward_mode=reward_mode,
        total=len(teams),
        challenges=challenges,
        teams=teams,
    )


@pytest.fixture
def event() -> BloodEvent:
    return BloodEvent(
        race_id="race",
        challenge_id="c1",
        challenge_name="easysql",
        direction="Web",
        blood=1,
        team_id="t1",
        team_name="A队",
        solve_time="2026-10-24 10:42:13",
        score=105,
        time_exact=True,
    )
