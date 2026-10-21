from __future__ import annotations

import pytest

from ctfblood.config import Settings
from ctfblood.models import Snapshot, SolveRecord
from ctfblood.service import BloodService
from ctfblood.store import Store

from .conftest import make_cell, make_challenge, make_snapshot, make_team


class FakeClient:
    def __init__(self, snapshots: list[Snapshot], solves: dict[tuple[str, str], SolveRecord] | None = None):
        self.snapshots = snapshots
        self.solves = solves or {}
        self.index = 0
        self.base = {
            "race_name": "测试赛",
            "start_time": "2026-10-24 09:30:00",
            "end_time": "2026-10-24 16:30:00",
        }
        self.closed = False

    async def fetch_snapshot(self) -> Snapshot:
        snapshot = self.snapshots[min(self.index, len(self.snapshots) - 1)]
        self.index += 1
        return snapshot

    async def fetch_solve(self, team_id: str, challenge_id: str) -> SolveRecord | None:
        return self.solves.get((team_id, challenge_id))

    async def fetch_base(self) -> dict:
        return self.base

    async def close(self) -> None:
        self.closed = True


class FakeNotifier:
    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[str] = []
        self.admin: list[str] = []
        self.fail_times = fail_times

    async def send(self, text: str) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("qq down")
        self.sent.append(text)

    async def send_admin(self, text: str) -> None:
        self.admin.append(text)


def _settings(tmp_path, **overrides) -> Settings:
    values = dict(
        base_url="http://ctf.test",
        race_id="race",
        viewer_key="k" * 32,
        group_id=10001,
        poll_interval=2.0,
        send_interval=1.0,
        catchup_mode="silent",
        db_path=str(tmp_path / "db.sqlite"),
    )
    values.update(overrides)
    return Settings(**values)


def _service(tmp_path, snapshots, notifier=None, **overrides):
    settings = _settings(tmp_path, **overrides)
    store = Store(settings.db_path)
    client = FakeClient(snapshots)
    notifier = notifier or FakeNotifier()
    service = BloodService(settings, client, store, notifier)
    return service, store, notifier, client


def _blood_snapshot(score: int = 100, solved: bool = True, rank: int = 1) -> Snapshot:
    challenge = make_challenge()
    team = make_team("t1", "A队", (make_cell(rank if solved else 0, solved),), score=score)
    return make_snapshot((challenge,), (team,))


@pytest.mark.asyncio
async def test_first_poll_silent_baseline(tmp_path) -> None:
    service, store, notifier, _ = _service(tmp_path, [_blood_snapshot()], catchup_mode="silent")
    try:
        assert await service.poll_once() == 0
        assert store.counts("race") == {"pending": 0, "sent": 1, "failed": 0}
        assert notifier.sent == []
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_first_poll_announce_sends_catchup(tmp_path) -> None:
    solve = SolveRecord("c1", "easysql", "Web", 105, "2026-10-24 10:42:13", "A")
    service, store, notifier, _ = _service(
        tmp_path,
        [_blood_snapshot()],
        catchup_mode="announce",
    )
    # inject the solve lookup
    service.client.solves[("t1", "c1")] = solve
    try:
        assert await service.poll_once() == 0
        assert store.counts("race")["pending"] == 1

        assert await service.send_once() is True
        assert len(notifier.sent) == 1
        assert "（补报）" in notifier.sent[0]
        assert "10:42:13" in notifier.sent[0]
        assert store.counts("race")["sent"] == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_new_blood_after_initial_baseline(tmp_path) -> None:
    empty = make_snapshot((make_challenge(),), (make_team("t1", "A队", (make_cell(0, False),)),))
    solve = SolveRecord("c1", "easysql", "Web", 105, "2026-10-24 10:42:13", "A")
    service, store, notifier, _ = _service(tmp_path, [empty, _blood_snapshot()])
    service.client.solves[("t1", "c1")] = solve
    try:
        assert await service.poll_once() == 0  # baseline
        assert await service.poll_once() == 1  # new blood
        assert await service.send_once() is True
        assert "🏆 一血" in notifier.sent[0]
        assert "A队" in notifier.sent[0]
        # idempotent
        assert await service.poll_once() == 0
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_missing_detail_uses_approximate_time(tmp_path) -> None:
    empty = make_snapshot((make_challenge(),), (make_team("t1", "A队", (make_cell(0, False),)),))
    service, store, notifier, _ = _service(tmp_path, [empty, _blood_snapshot()])
    try:
        await service.poll_once()
        await service.poll_once()
        await service.send_once()
        assert "时间未知" in notifier.sent[0]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_send_failure_is_retried(tmp_path, monkeypatch) -> None:
    service, store, notifier, _ = _service(
        tmp_path,
        [_blood_snapshot()],
        notifier=FakeNotifier(fail_times=1),
        catchup_mode="announce",
    )
    try:
        monkeypatch.setattr("ctfblood.service._after", lambda seconds: "2000-01-01 00:00:00")
        await service.poll_once()
        assert await service.send_once() is False
        assert store.counts("race")["pending"] == 1

        assert await service.send_once() is True
        assert store.counts("race")["sent"] == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_reset_clears_state(tmp_path) -> None:
    high = _blood_snapshot(score=1000)
    zero = make_snapshot(
        (make_challenge(),),
        (make_team("t1", "A队", (make_cell(0, False),), score=0),),
    )
    service, store, notifier, _ = _service(tmp_path, [high, zero, zero])
    try:
        await service.poll_once()  # baseline, sent=1, total_score=1000
        assert store.counts("race")["sent"] == 1

        await service.poll_once()  # first drop
        await service.poll_once()  # second drop -> reset
        assert store.counts("race") == {"pending": 0, "sent": 0, "failed": 0}
        assert any("重置" in message for message in notifier.sent)
        assert store.get_meta("initialized:race") == ""
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_fingerprint_change_skips_one_cycle(tmp_path) -> None:
    first = make_snapshot((make_challenge("c1"),), ())
    second = make_snapshot((make_challenge("c2"),), ())
    service, store, _, _ = _service(tmp_path, [first, second, second])
    try:
        await service.poll_once()  # baseline c1
        assert await service.poll_once() == 0  # fingerprint changed -> skip
        state = store.get_state("race")
        assert state is not None
        assert state["fingerprint"] == second.fingerprint
        assert await service.poll_once() == 0  # normal, no bloods
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_reward_mode_zero_does_nothing(tmp_path) -> None:
    snapshot = make_snapshot(
        (make_challenge(),),
        (make_team("t1", "A队", (make_cell(0, True),)),),
        reward_mode=0,
    )
    service, store, notifier, _ = _service(tmp_path, [snapshot])
    try:
        assert await service.poll_once() == 0
        assert store.counts("race") == {"pending": 0, "sent": 0, "failed": 0}
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_status_text(tmp_path) -> None:
    service, _, _, _ = _service(tmp_path, [_blood_snapshot()])
    try:
        await service.load_race_info()
        text = service.status_text(bot_ready=True)
        assert "测试赛" in text
        assert "Bot：已连接" in text
    finally:
        await service.close()
