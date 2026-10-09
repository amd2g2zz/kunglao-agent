# -*- coding: utf-8 -*-
"""tests/test_belief_reconcile_600.py — environment-belief reconciliation.

RED-first pins for the two reconciliation faces:

  A. provider_health latest-entry-wins: a provider counts as failed ONLY
     while its LATEST in-window entry is a fail — an ok entry newer than
     the last fail clears the demotion (evidence beats wall clock); the
     no-ok window semantics are byte-identical to the old scan. The ok
     touch point is the SAME append-only record face the worker runtime
     already uses for fails (verified: no other in-repo caller records).

  B. loop-layer API-failure backoff: consecutive quota-class rc=1
     dispatch failures grow an exponential backoff on that lane's next
     attempt — base is the existing luby base, the exponent is capped,
     ANY successful act resets it, non-quota rc=1 never triggers it,
     every retreat step emits ONE audit-stream row, and the lane keeps
     re-probing forever (a hold, never a wall-clock cliff).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "scripts" / "e2e"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import provider_health as ph  # noqa: E402
from e2e import audit, checkpoints, llm_faces, model  # noqa: E402


def _ts(hours_ago: float) -> str:
    when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Face A — provider_health latest-entry-wins
# ---------------------------------------------------------------------------


class TestProviderHealthLatestEntryWins:
    def test_fail_then_ok_clears(self, tmp_path):
        ph.record(tmp_path, "jadx", "fail", reason="timeout",
                  ts=_ts(2))
        ph.record(tmp_path, "jadx", "ok", reason="recovered",
                  ts=_ts(1))
        assert ph.recent_failures(tmp_path) == {}

    def test_ok_then_fail_stays_failed(self, tmp_path):
        ph.record(tmp_path, "jadx", "ok", reason="was fine", ts=_ts(2))
        ph.record(tmp_path, "jadx", "fail", reason="crashed", ts=_ts(1))
        out = ph.recent_failures(tmp_path)
        assert out["jadx"]["reason"] == "crashed"
        assert out["jadx"]["ts"] == _ts(1)

    def test_ok_older_than_fail_inside_window_does_not_clear(self, tmp_path):
        ph.record(tmp_path, "jadx", "ok", reason="old", ts=_ts(5))
        ph.record(tmp_path, "jadx", "fail", reason="new", ts=_ts(4))
        assert "jadx" in ph.recent_failures(tmp_path)

    def test_window_semantics_unchanged_no_ok(self, tmp_path):
        ph.record(tmp_path, "jadx", "fail", reason="fresh", ts=_ts(1))
        ph.record(tmp_path, "baksmali", "fail", reason="stale",
                  ts=_ts(25))
        out = ph.recent_failures(tmp_path)
        assert "jadx" in out
        assert "baksmali" not in out  # outside the window: absent

    def test_fail_inside_window_beats_ok_outside_window(self, tmp_path):
        # ok older than the window cannot clear a newer in-window fail
        ph.record(tmp_path, "jadx", "ok", reason="ancient", ts=_ts(30))
        ph.record(tmp_path, "jadx", "fail", reason="recent", ts=_ts(2))
        assert "jadx" in ph.recent_failures(tmp_path)

    def test_ok_inside_window_cannot_be_cleared_by_stale_fail(self, tmp_path):
        # a fail older than the window with an in-window ok: cleared
        # (same outcome as the old scan — the fail was already expired)
        ph.record(tmp_path, "jadx", "fail", reason="expired", ts=_ts(30))
        ph.record(tmp_path, "jadx", "ok", reason="recovered", ts=_ts(1))
        assert ph.recent_failures(tmp_path) == {}

    def test_record_ok_is_append_only(self, tmp_path):
        ph.record(tmp_path, "jadx", "fail", reason="timeout", ts=_ts(2))
        path = ph.record(tmp_path, "jadx", "ok", reason="fine", ts=_ts(1))
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["jadx"]
        assert [e["outcome"] for e in entries] == ["fail", "ok"]
        assert entries[0]["reason"] == "timeout"  # untouched

    def test_corrupt_file_stays_fail_open(self, tmp_path):
        (tmp_path / "provider_health.json").write_text(
            "{not json", encoding="utf-8")
        assert ph.recent_failures(tmp_path) == {}

    def test_unparseable_ts_entries_are_skipped(self, tmp_path):
        ph.record(tmp_path, "jadx", "fail", reason="good", ts=_ts(1))
        path = tmp_path / "provider_health.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["jadx"].append({"outcome": "ok", "reason": "no-ts"})
        path.write_text(json.dumps(data), encoding="utf-8")
        # the ok carries no parseable ts: it cannot order itself against
        # the fail, so the in-window fail stays the latest KNOWN entry
        assert "jadx" in ph.recent_failures(tmp_path)


class TestRouterDemotionReconciles:
    """The success touch point end-to-end: the same record face the
    worker runtime already uses for fails now clears the router's
    demotion once a success is recorded through it."""

    _TOOLS = [{"name": "jadx-decompile", "provider": "jadx",
               "capability": "android:java-source",
               "produces": ["java-source"], "quality": {"java-source": "high"},
               "requires": [], "cost_hint": {"mem_gb": 2}}]

    def test_demote_then_clear_through_the_record_face(self, tmp_path):
        from route_capability import select_providers
        ws = tmp_path / "ws"
        ws.mkdir()
        state = {"provider_failures": ph.recent_failures(ws)}
        demoted = select_providers("java-source", self._TOOLS, state)
        assert demoted["providers"][0]["recent_failure"] is False
        ph.record(ws, "jadx", "fail", reason="oom", ts=_ts(1))
        state = {"provider_failures": ph.recent_failures(ws)}
        demoted = select_providers("java-source", self._TOOLS, state)
        assert demoted["providers"][0]["recent_failure"] is True
        # the reconciliation: a success through the same face clears it
        ph.record(ws, "jadx", "ok", reason="clean run", ts=_ts(0))
        state = {"provider_failures": ph.recent_failures(ws)}
        recovered = select_providers("java-source", self._TOOLS, state)
        assert recovered["providers"][0]["recent_failure"] is False


# ---------------------------------------------------------------------------
# Face B — loop-layer quota-class backoff (dispatch/settle path)
# ---------------------------------------------------------------------------

QUOTA_403 = ("API Error 403: request failed: your credit balance is too "
             "low to access the API")
QUOTA_429 = "API Error 429: rate limit exceeded: usage cap reached"


class TestQuotaClassification:
    def test_403_insufficient_balance_matches(self):
        assert checkpoints._is_quota_class_stderr(QUOTA_403) is True

    def test_429_usage_cap_matches(self):
        assert checkpoints._is_quota_class_stderr(QUOTA_429) is True

    def test_real_worker_failure_does_not_match(self):
        assert checkpoints._is_quota_class_stderr(
            "Traceback (most recent call last): ... worker crashed") is False

    def test_empty_stderr_fails_open(self):
        assert checkpoints._is_quota_class_stderr("") is False
        assert checkpoints._is_quota_class_stderr(None) is False

    def test_word_bounded_codes(self):
        assert checkpoints._is_quota_class_stderr("exit E4031 malformed") \
            is False
        assert checkpoints._is_quota_class_stderr("http 429 returned") is True


class TestBackoffShape:
    def test_first_retreat_is_one_base(self):
        assert checkpoints._quota_backoff_delay_s(1) == \
            checkpoints.LUBY_BASE_S

    def test_growth_is_monotone_then_flat(self):
        delays = [checkpoints._quota_backoff_delay_s(n)
                  for n in range(1, 12)]
        capped = checkpoints.QUOTA_BACKOFF_MAX_EXP
        for i in range(1, len(delays)):
            if i <= capped:
                assert delays[i] == delays[i - 1] * 2  # exponential growth
            else:
                assert delays[i] == delays[i - 1]  # the exponent cap holds
        assert len(set(delays[capped:])) == 1  # bounded, never a cliff

    def test_cap_is_the_only_new_constant(self):
        # the base is THE existing luby base — no parallel wall-clock scale
        assert checkpoints._quota_backoff_delay_s(
            checkpoints.QUOTA_BACKOFF_MAX_EXP + 1) \
            == checkpoints.LUBY_BASE_S * (2 ** checkpoints.QUOTA_BACKOFF_MAX_EXP)


class _FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def monotonic(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def _make_ctx(tmp_path: Path, clock: _FakeClock):
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    state = model.RunState(
        run_id="r1", unit="u1", family="smoke", repo=str(ROOT),
        task_dir=str(tmp_path), ws=str(ws),
        evidence_dir=str(tmp_path / "ev"), budget_seconds=10000,
        llm_mode="dry", started_ts="t", started_monotonic=0.0,
        anchors={"goal_verbatim": "g", "success_criterion": "s",
                 "verification_method": "reproduction"})
    return checkpoints.RunContext(state=state, runner=None, face=None,
                                  clock=clock, sleep_fn=lambda _s: None)


def _act(claim: str, outcome: str, rc, stderr: str = ""):
    return llm_faces.ActRecord(
        claim, "dry", outcome,
        {"rc": rc, "stderr_tail": stderr, "duration_ms": 10})


def _rows(ws: Path, action: str) -> list[dict]:
    path = audit.audit_path(ws)
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("action") != action:
            continue
        if isinstance(row.get("detail"), str):  # the stream's detail face
            try:
                row["detail"] = json.loads(row["detail"])
            except ValueError:
                pass
        out.append(row)
    return out


class TestSettleBackoff:
    def test_quota_failures_grow_and_emit_one_row_each(self, tmp_path):
        clock = _FakeClock()
        ctx = _make_ctx(tmp_path, clock)
        dispatched: set = set()
        for i in range(1, 4):
            checkpoints._land_dispatch(
                ctx, "C-1", _act("C-1", "ERROR", 1, QUOTA_403),
                dispatched, {"acts": []})
            assert ctx.quota_streak["C-1"] == i
        rows = _rows(ctx.ws, "dispatch_backoff")
        assert len(rows) == 3  # every retreat step is observable
        delays = [r["detail"]["delay_s"] for r in rows]
        assert delays == [checkpoints._quota_backoff_delay_s(n)
                          for n in (1, 2, 3)]
        assert rows[2]["detail"]["consecutive"] == 3

    def test_success_resets(self, tmp_path):
        clock = _FakeClock()
        ctx = _make_ctx(tmp_path, clock)
        for i in range(1, 3):
            checkpoints._land_dispatch(
                ctx, "C-1", _act("C-1", "ERROR", 1, QUOTA_429),
                set(), {"acts": []})
        assert ctx.quota_streak["C-1"] == 2
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "DISPATCHED", 0), set(), {"acts": []})
        assert ctx.quota_streak.get("C-1", 0) == 0
        assert ctx.quota_hold_until.get("C-1", 0.0) == 0.0
        # the next failure starts from the base again (memory released)
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "ERROR", 1, QUOTA_429),
            set(), {"acts": []})
        assert ctx.quota_streak["C-1"] == 1

    def test_non_quota_rc1_never_triggers_and_breaks_streak(self, tmp_path):
        clock = _FakeClock()
        ctx = _make_ctx(tmp_path, clock)
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "ERROR", 1, "segfault at 0x0"),
            set(), {"acts": []})
        assert ctx.quota_streak.get("C-1", 0) == 0
        assert len(_rows(ctx.ws, "dispatch_backoff")) == 0
        # an intervening real failure breaks the consecutive quota run
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "ERROR", 1, QUOTA_403),
            set(), {"acts": []})
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "ERROR", 1, "worker assert failed"),
            set(), {"acts": []})
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "ERROR", 1, QUOTA_403),
            set(), {"acts": []})
        assert ctx.quota_streak["C-1"] == 1  # the storm did not survive

    def test_timeout_does_not_trigger(self, tmp_path):
        clock = _FakeClock()
        ctx = _make_ctx(tmp_path, clock)
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "TIMEOUT", -1,
                             "TIMEOUT after 1800s: claude -p"),
            set(), {"acts": []})
        assert ctx.quota_streak.get("C-1", 0) == 0
        assert len(_rows(ctx.ws, "dispatch_backoff")) == 0


class TestLaneHold:
    def test_hold_gates_the_next_attempt(self, tmp_path):
        clock = _FakeClock()
        ctx = _make_ctx(tmp_path, clock)
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "ERROR", 1, QUOTA_403),
            set(), {"acts": []})
        assert ctx.quota_hold_until["C-1"] > clock.monotonic()
        # the lane holds: no launch, no attempt row, no dispatched mark
        dispatched: set = set()
        request, _handle = checkpoints._launch_dispatch(ctx, "C-1",
                                                        dispatched)
        assert request is None
        assert "C-1" not in dispatched
        assert len(_rows(ctx.ws, "dispatch_attempt")) == 0

    def test_hold_expires_and_re_probes(self, tmp_path):
        clock = _FakeClock()
        ctx = _make_ctx(tmp_path, clock)
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "ERROR", 1, QUOTA_403),
            set(), {"acts": []})
        hold = ctx.quota_hold_until["C-1"]
        assert checkpoints._quota_hold_active(ctx, "C-1") is True
        clock.advance((hold - clock.monotonic()) + 1.0)
        assert checkpoints._quota_hold_active(ctx, "C-1") is False
        # a fresh lane was never held
        assert checkpoints._quota_hold_active(ctx, "C-2") is False


class TestCorpusReplay:
    def test_storm_between_two_successful_act(self, tmp_path):
        """The round-2 corpus shape: success, then a fail-fast quota
        storm, then success — the backoff engages during the storm and
        releases on the first success."""
        clock = _FakeClock()
        ctx = _make_ctx(tmp_path, clock)
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "DISPATCHED", 0), set(), {"acts": []})
        assert ctx.quota_streak.get("C-1", 0) == 0
        for _ in range(4):
            checkpoints._land_dispatch(
                ctx, "C-1", _act("C-1", "ERROR", 1, QUOTA_403),
                set(), {"acts": []})
        assert ctx.quota_streak["C-1"] == 4
        assert ctx.quota_hold_until["C-1"] > clock.monotonic()
        checkpoints._land_dispatch(
            ctx, "C-1", _act("C-1", "DISPATCHED", 0), set(), {"acts": []})
        assert ctx.quota_streak.get("C-1", 0) == 0
        assert ctx.quota_hold_until.get("C-1", 0.0) == 0.0
        rows = _rows(ctx.ws, "dispatch_backoff")
        assert len(rows) == 4  # one observable row per retreat step


class TestAuditVocabulary:
    def test_dispatch_backoff_is_a_registered_action(self):
        assert "dispatch_backoff" in audit.AUDIT_ACTIONS

    def test_emit_dispatch_backoff_row_shape(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "runs" / "logs").mkdir(parents=True)
        ok = audit.emit_dispatch_backoff(
            ws, "C-1", consecutive=3, delay_s=7200, capped=False)
        assert ok is True
        row = _rows(ws, "dispatch_backoff")[0]
        assert row["claim"] == "C-1"
        assert row["detail"] == {"claim": "C-1", "consecutive": 3,
                                 "delay_s": 7200, "capped": False}
        assert row["exit"] == 1
