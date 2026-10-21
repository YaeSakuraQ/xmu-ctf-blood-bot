from __future__ import annotations

import httpx
import pytest

from ctfblood.api import CTFAPIError, CTFClient, SchemaError
from ctfblood.config import Settings


def _settings() -> Settings:
    return Settings(
        base_url="http://ctf.test",
        race_id="race",
        viewer_key="secret-key",
        group_id=1,
    )


def _challenge(challenge_id: str = "c1", name: str = "easysql") -> dict:
    return {"checkpoint_id": challenge_id, "name": name, "direction": "Web", "score": 100}


def _team(team_id: str, name: str, cells: list[dict], score: int = 0) -> dict:
    return {
        "resource_id": team_id,
        "name": name,
        "score": score,
        "solved": sum(1 for cell in cells if cell.get("is_solved")),
        "checker_score": cells,
    }


def _rank_payload(teams: list[dict], challenges: list[dict], total: int | None = None) -> dict:
    return {
        "code": "AD-000000",
        "message": "",
        "data": {
            "checker_detail": challenges,
            "rank_detail": teams,
            "reward_mode": 1,
            "total": total if total is not None else len(teams),
        },
    }


@pytest.mark.asyncio
async def test_fetch_snapshot_parses() -> None:
    payload = _rank_payload(
        [_team("t1", "A队", [{"rank": 1, "is_solved": True}], score=105)],
        [_challenge()],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = CTFClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        snapshot = await client.fetch_snapshot()
    finally:
        await client.close()

    assert len(snapshot.teams) == 1
    assert snapshot.teams[0].name == "A队"
    assert snapshot.teams[0].cells[0].rank == 1
    assert snapshot.teams[0].cells[0].is_solved is True
    assert snapshot.challenges[0].name == "easysql"
    assert snapshot.total_score == 105
    assert snapshot.total_solved == 1


@pytest.mark.asyncio
async def test_fetch_snapshot_paginates() -> None:
    challenges = [_challenge()]
    page_one = _rank_payload([_team("t1", "A队", [{"rank": 0, "is_solved": False}])], challenges, total=2)
    page_two = _rank_payload([_team("t2", "B队", [{"rank": 0, "is_solved": False}])], challenges, total=2)

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        return httpx.Response(200, json=page_two if page == "2" else page_one)

    client = CTFClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        snapshot = await client.fetch_snapshot()
    finally:
        await client.close()

    assert [team.team_id for team in snapshot.teams] == ["t1", "t2"]


@pytest.mark.asyncio
async def test_error_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": "AD-002005", "message": "无操作权限"})

    client = CTFClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CTFAPIError) as exc:
            await client.fetch_snapshot()
    finally:
        await client.close()

    assert exc.value.code == "AD-002005"
    assert "无操作权限" in str(exc.value)


@pytest.mark.asyncio
async def test_schema_mismatch_raises() -> None:
    payload = _rank_payload(
        [_team("t1", "A队", [])],
        [_challenge()],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = CTFClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(SchemaError):
            await client.fetch_snapshot()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_fetch_solve() -> None:
    payload = {
        "code": "AD-000000",
        "data": [
            {
                "creator": "member",
                "score": 105,
                "create_time": "2026-10-24 10:42:13",
                "checkpoint": {"resource_id": "c1", "name": "easysql", "direction": "Web"},
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rank/t1/")
        return httpx.Response(200, json=payload)

    client = CTFClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        record = await client.fetch_solve("t1", "c1")
    finally:
        await client.close()

    assert record is not None
    assert record.score == 105
    assert record.create_time == "2026-10-24 10:42:13"


@pytest.mark.asyncio
async def test_redacts_viewer_key() -> None:
    client = CTFClient(_settings())
    try:
        assert client._redact("url?viewer_key=secret-key") == "url?viewer_key=***"
    finally:
        await client.close()
