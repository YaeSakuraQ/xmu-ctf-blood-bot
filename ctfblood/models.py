"""Typed data structures shared by the collector, detector, store and bot."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Challenge:
    challenge_id: str
    name: str
    direction: str
    score: int


@dataclass(frozen=True)
class Cell:
    rank: int
    is_solved: bool


@dataclass(frozen=True)
class Team:
    team_id: str
    name: str
    score: int
    solved: int
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class Snapshot:
    race_id: str
    reward_mode: int
    total: int
    challenges: tuple[Challenge, ...]
    teams: tuple[Team, ...]

    @property
    def fingerprint(self) -> str:
        """Stable fingerprint of challenge order.

        ``checker_score`` is aligned to ``checker_detail`` by index, so if the
        platform inserts/removes/reorders challenges between two polls we must
        not interpret the old index against the new list. The service skips a
        cycle when this changes.
        """

        payload = "|".join(challenge.challenge_id for challenge in self.challenges)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    @property
    def total_score(self) -> int:
        return sum(team.score for team in self.teams)

    @property
    def total_solved(self) -> int:
        return sum(1 for team in self.teams for cell in team.cells if cell.is_solved)

    def challenge_by_id(self, challenge_id: str) -> Challenge | None:
        return next((c for c in self.challenges if c.challenge_id == challenge_id), None)


@dataclass(frozen=True)
class Candidate:
    """A (challenge, blood level, team) tuple that should be announced."""

    challenge: Challenge
    blood: int
    team: Team


@dataclass(frozen=True)
class SolveRecord:
    challenge_id: str
    challenge_name: str
    direction: str
    score: int
    create_time: str
    creator: str


@dataclass(frozen=True)
class BloodEvent:
    race_id: str
    challenge_id: str
    challenge_name: str
    direction: str
    blood: int
    team_id: str
    team_name: str
    solve_time: str | None
    score: int | None
    time_exact: bool
    catchup: bool = False
    detected_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.race_id, self.challenge_id, self.blood)


@dataclass(frozen=True)
class StoredEvent:
    """A row from the announcements table."""

    race_id: str
    challenge_id: str
    challenge_name: str
    direction: str
    blood: int
    team_id: str
    team_name: str
    solve_time: str | None
    score: int | None
    time_exact: bool
    catchup: bool
    status: str
    attempts: int

    def to_event(self) -> BloodEvent:
        return BloodEvent(
            race_id=self.race_id,
            challenge_id=self.challenge_id,
            challenge_name=self.challenge_name,
            direction=self.direction,
            blood=self.blood,
            team_id=self.team_id,
            team_name=self.team_name,
            solve_time=self.solve_time,
            score=self.score,
            time_exact=self.time_exact,
            catchup=self.catchup,
        )
