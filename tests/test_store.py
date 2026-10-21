from __future__ import annotations

from ctfblood.models import BloodEvent
from ctfblood.store import Store


def _event(challenge_id: str = "c1", blood: int = 1, race_id: str = "race", team: str = "t1") -> BloodEvent:
    return BloodEvent(
        race_id=race_id,
        challenge_id=challenge_id,
        challenge_name=f"题目{challenge_id}",
        direction="Web",
        blood=blood,
        team_id=team,
        team_name=f"队伍{team}",
        solve_time="2026-10-24 10:42:13",
        score=105,
        time_exact=True,
    )


def test_add_is_idempotent(tmp_path) -> None:
    store = Store(str(tmp_path / "db.sqlite"))
    try:
        assert store.add(_event()) is True
        assert store.add(_event()) is False
        assert store.announced_keys("race") == {("c1", 1)}
        assert store.has_any("race")
        assert store.counts("race") == {"pending": 1, "sent": 0, "failed": 0}
    finally:
        store.close()


def test_pending_and_mark_sent(tmp_path) -> None:
    store = Store(str(tmp_path / "db.sqlite"))
    try:
        store.add(_event(), now="2026-10-24 10:00:00")
        row = store.next_pending("race", now="2026-10-24 10:00:01")
        assert row is not None
        assert row.team_name == "队伍t1"

        store.mark_sent((row.race_id, row.challenge_id, row.blood), "hello", now="2026-10-24 10:00:02")
        assert store.counts("race") == {"pending": 0, "sent": 1, "failed": 0}
        assert store.next_pending("race", now="2026-10-24 10:00:03") is None
    finally:
        store.close()


def test_failed_retries_then_gives_up(tmp_path) -> None:
    store = Store(str(tmp_path / "db.sqlite"))
    try:
        store.add(_event("c2"))
        key = ("race", "c2", 1)

        status = store.mark_failed(
            key, "boom", next_attempt_at="2026-10-24 10:00:05", max_attempts=2
        )
        assert status == "pending"
        assert store.counts("race")["pending"] == 1

        status = store.mark_failed(
            key, "boom again", next_attempt_at="2026-10-24 10:00:10", max_attempts=2
        )
        assert status == "failed"
        assert store.counts("race")["failed"] == 1
        assert store.next_pending("race", now="2026-10-24 11:00:00") is None
    finally:
        store.close()


def test_race_filter(tmp_path) -> None:
    store = Store(str(tmp_path / "db.sqlite"))
    try:
        store.add(_event("c1", race_id="other"))
        assert store.next_pending("race") is None
        assert store.next_pending("other") is not None
    finally:
        store.close()


def test_state_and_clear(tmp_path) -> None:
    store = Store(str(tmp_path / "db.sqlite"))
    try:
        store.set_meta("initialized:race", "1")
        store.set_state(
            "race",
            fingerprint="abc",
            total_score=100,
            total_solved=2,
            drop_streak=1,
            last_poll_at="2026-10-24 10:00:00",
        )
        state = store.get_state("race")
        assert state is not None
        assert state["fingerprint"] == "abc"
        assert state["total_score"] == 100
        assert store.get_meta("initialized:race") == "1"

        store.clear_race("race")
        assert store.get_state("race") is None
        assert store.get_meta("initialized:race") == ""
        assert store.has_any("race") is False
    finally:
        store.close()
