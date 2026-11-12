"""Certified fact dates follow the linter's local calendar."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

import _factories
import lint_facts


@pytest.mark.parametrize("today", [date(2026, 11, 12), date(2031, 3, 7)])
def test_certified_fact_is_fresh_on_current_date(tmp_path, monkeypatch, today):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(today.year, today.month, today.day, tzinfo=tz)

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(today.year, today.month, today.day)

    monkeypatch.setattr(_factories, "datetime", FrozenDateTime)
    path = _factories.write_certified_fact(tmp_path, "F001", "C-001")
    fm, body, error = lint_facts.parse_frontmatter(path.read_text())
    assert error is None
    assert date.fromisoformat(str(fm["created"])) <= date.fromisoformat(str(fm["last_reviewed"]))
    assert str(fm["created"]) == str(fm["last_reviewed"]) == today.isoformat()

    monkeypatch.setattr(lint_facts, "datetime", SimpleNamespace(date=FrozenDate))
    issues = lint_facts.lint_fact("F001", fm, {"F001"}, body)
    assert "STALE_LAST_REVIEWED" not in {issue[1] for issue in issues}

    aged_today = today + timedelta(days=lint_facts.STALENESS_WARN_DAYS + 1)
    class AgedDate(date):
        @classmethod
        def today(cls):
            return cls(aged_today.year, aged_today.month, aged_today.day)

    monkeypatch.setattr(lint_facts, "datetime", SimpleNamespace(date=AgedDate))
    issues = lint_facts.lint_fact("F001", fm, {"F001"}, body)
    assert "STALE_LAST_REVIEWED" in {issue[1] for issue in issues}
