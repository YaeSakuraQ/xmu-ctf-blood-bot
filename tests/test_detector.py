from __future__ import annotations

from ctfblood.detector import blood_table, find_candidates, validate_snapshot
from ctfblood.models import Snapshot

from .conftest import make_cell, make_challenge, make_snapshot, make_team


def test_find_candidates_three_bloods() -> None:
    challenge = make_challenge()
    teams = (
        make_team("t1", "A队", (make_cell(1, True),)),
        make_team("t2", "B队", (make_cell(2, True),)),
        make_team("t3", "C队", (make_cell(3, True),)),
        make_team("t4", "D队", (make_cell(4, True),)),
    )
    snapshot = make_snapshot((challenge,), teams)

    candidates = find_candidates(snapshot, set())

    assert [candidate.blood for candidate in candidates] == [1, 2, 3]
    assert [candidate.team.name for candidate in candidates] == ["A队", "B队", "C队"]


def test_announced_and_unsolved_are_filtered() -> None:
    challenge = make_challenge()
    teams = (
        make_team("t1", "A队", (make_cell(1, True),)),
        make_team("t2", "B队", (make_cell(2, False),)),
        make_team("t3", "C队", (make_cell(0, False),)),
    )
    snapshot = make_snapshot((challenge,), teams)

    assert find_candidates(snapshot, {("c1", 1)}) == []
    assert len(find_candidates(snapshot, set())) == 1


def test_reward_mode_zero_has_no_bloods() -> None:
    challenge = make_challenge()
    teams = (make_team("t1", "A队", (make_cell(0, True),)),)
    snapshot = make_snapshot((challenge,), teams, reward_mode=0)

    assert find_candidates(snapshot, set()) == []
    assert "reward_mode" in validate_snapshot(snapshot)[0]


def test_levels_filter() -> None:
    challenge = make_challenge()
    teams = (
        make_team("t1", "A队", (make_cell(1, True),)),
        make_team("t2", "B队", (make_cell(2, True),)),
    )
    snapshot = make_snapshot((challenge,), teams)

    assert [c.blood for c in find_candidates(snapshot, set(), levels=(1,))] == [1]


def test_duplicate_rank_is_deduped() -> None:
    challenge = make_challenge()
    teams = (
        make_team("t1", "A队", (make_cell(1, True),)),
        make_team("t2", "B队", (make_cell(1, True),)),
    )
    snapshot = make_snapshot((challenge,), teams)

    candidates = find_candidates(snapshot, set())
    assert len(candidates) == 1


def test_fingerprint_tracks_challenge_order() -> None:
    one = make_snapshot((make_challenge("c1"), make_challenge("c2")), ())
    two = make_snapshot((make_challenge("c2"), make_challenge("c1")), ())
    same = make_snapshot((make_challenge("c1"), make_challenge("c2")), ())

    assert one.fingerprint != two.fingerprint
    assert one.fingerprint == same.fingerprint


def test_blood_table_groups_by_challenge() -> None:
    challenge = make_challenge()
    teams = (
        make_team("t1", "A队", (make_cell(1, True),)),
        make_team("t2", "B队", (make_cell(2, True),)),
    )
    snapshot = make_snapshot((challenge,), teams)

    table = blood_table(snapshot)
    assert len(table) == 1
    assert [blood for blood, _ in table[0][1]] == [1, 2]


def test_totals() -> None:
    challenge = make_challenge()
    teams = (
        make_team("t1", "A队", (make_cell(1, True),), score=105),
        make_team("t2", "B队", (make_cell(0, False),), score=0),
    )
    snapshot = make_snapshot((challenge,), teams)

    assert snapshot.total_score == 105
    assert snapshot.total_solved == 1
    assert snapshot.challenge_by_id("c1") is challenge
    assert snapshot.challenge_by_id("missing") is None
    assert isinstance(snapshot, Snapshot)
