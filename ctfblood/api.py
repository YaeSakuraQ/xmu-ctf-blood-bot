"""HTTP client for the cyber-range public screen API.

The bot deliberately uses only the public, read-only endpoints. It never logs
in and never sends a write request, so a compromised bot host cannot modify
the contest.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings
from .models import Cell, Challenge, Snapshot, SolveRecord, Team

logger = logging.getLogger(__name__)

OK_CODE = "AD-000000"


class CTFAPIError(RuntimeError):
    """The platform returned an error envelope or an invalid response."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class SchemaError(CTFAPIError):
    """The response shape changed and cannot be interpreted safely."""


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_challenge(raw: dict[str, Any]) -> Challenge:
    challenge_id = str(raw.get("checkpoint_id") or "").strip()
    if not challenge_id:
        raise SchemaError("BAD-CHALLENGE", "checker_detail 中缺少 checkpoint_id")
    return Challenge(
        challenge_id=challenge_id,
        name=str(raw.get("name") or "未知题目"),
        direction=str(raw.get("direction") or "Unknown"),
        score=_as_int(raw.get("score")),
    )


def _parse_team(raw: dict[str, Any], challenge_count: int) -> Team:
    team_id = str(raw.get("resource_id") or "").strip()
    if not team_id:
        raise SchemaError("BAD-TEAM", "rank_detail 中缺少 resource_id")
    cells_raw = raw.get("checker_score") or []
    if len(cells_raw) != challenge_count:
        raise SchemaError(
            "BAD-CELLS",
            f"队伍 {raw.get('name')!r} 的 checker_score 长度 {len(cells_raw)} "
            f"与题目数 {challenge_count} 不一致，榜单结构可能已变化",
        )
    cells = tuple(
        Cell(rank=_as_int(cell.get("rank")), is_solved=bool(cell.get("is_solved")))
        for cell in cells_raw
    )
    return Team(
        team_id=team_id,
        name=str(raw.get("name") or "未知队伍"),
        score=_as_int(raw.get("score")),
        solved=_as_int(raw.get("solved")),
        cells=cells,
    )


class CTFClient:
    """Async client for ``/api/ct/public/jeopardy_race/...``."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.request_timeout, connect=min(3.0, settings.request_timeout)),
            headers={
                "Accept": "application/json",
                "User-Agent": "xmu-ctf-blood-bot/0.1 (+https://github.com/YaeSakuraQ)",
            },
            follow_redirects=True,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def _redact(self, text: str) -> str:
        """Never let the viewer key end up in logs or chat error messages."""

        if self.settings.viewer_key:
            return text.replace(self.settings.viewer_key, "***")
        return text

    async def _get(self, path: str, **params: Any) -> Any:
        params["viewer_key"] = self.settings.viewer_key
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise CTFAPIError("NETWORK", self._redact(f"请求 {path} 失败: {exc}")) from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            code = str(payload.get("code") or f"HTTP-{response.status_code}")
            message = str(payload.get("message") or response.text[:200])
            raise CTFAPIError(code, self._redact(message))

        try:
            payload = response.json()
        except ValueError as exc:
            raise CTFAPIError("BAD-JSON", f"{path} 返回了非 JSON 内容") from exc

        if payload.get("code") != OK_CODE:
            raise CTFAPIError(
                str(payload.get("code") or "UNKNOWN"),
                str(payload.get("message") or "未知错误"),
            )
        return payload.get("data")

    async def fetch_base(self) -> dict[str, Any]:
        data = await self._get(self.settings.base_info_path)
        if not isinstance(data, dict):
            raise SchemaError("BAD-BASE", "base 接口返回结构异常")
        return data

    async def fetch_snapshot(self) -> Snapshot:
        """Fetch the full scoreboard, following pagination when needed."""

        challenges: tuple[Challenge, ...] | None = None
        teams: list[Team] = []
        total = 0
        page = 1
        while page <= 50:
            data = await self._get(
                self.settings.team_path,
                page=page,
                per_page=1000,
            )
            if not isinstance(data, dict):
                raise SchemaError("BAD-RANK", "rank 接口返回结构异常")

            raw_challenges = data.get("checker_detail") or []
            if challenges is None:
                challenges = tuple(_parse_challenge(raw) for raw in raw_challenges)
            elif len(challenges) != len(raw_challenges):
                raise SchemaError("BAD-CHALLENGES", "分页之间题目数量不一致")

            raw_teams = data.get("rank_detail") or []
            total = _as_int(data.get("total"), len(teams) + len(raw_teams))
            teams.extend(_parse_team(raw, len(challenges)) for raw in raw_teams)

            if not raw_teams or len(teams) >= total:
                break
            page += 1

        if challenges is None:
            challenges = ()

        return Snapshot(
            race_id=self.settings.race_id,
            reward_mode=_as_int(data.get("reward_mode")),
            total=total or len(teams),
            challenges=challenges,
            teams=tuple(teams),
        )

    async def fetch_team_solves(self, team_id: str) -> list[SolveRecord]:
        data = await self._get(f"{self.settings.team_path}{team_id}/")
        if not isinstance(data, list):
            raise SchemaError("BAD-TEAM-DETAIL", "单队时间线接口返回结构异常")
        records: list[SolveRecord] = []
        for raw in data:
            checkpoint = raw.get("checkpoint") or {}
            challenge_id = str(checkpoint.get("resource_id") or "").strip()
            if not challenge_id:
                continue
            records.append(
                SolveRecord(
                    challenge_id=challenge_id,
                    challenge_name=str(checkpoint.get("name") or "未知题目"),
                    direction=str(checkpoint.get("direction") or "Unknown"),
                    score=_as_int(raw.get("score")),
                    create_time=str(raw.get("create_time") or ""),
                    creator=str(raw.get("creator") or ""),
                )
            )
        return records

    async def fetch_solve(self, team_id: str, challenge_id: str) -> SolveRecord | None:
        records = await self.fetch_team_solves(team_id)
        return next((record for record in records if record.challenge_id == challenge_id), None)
