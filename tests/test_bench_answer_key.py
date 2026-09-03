# -*- coding: utf-8 -*-
"""B2 (#823): bench_answer_key — key schema validation, IOC normalization,
mechanical matchers, and leak-free task-spec PQ generation."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bench_answer_key as ak


# ---------- IOC normalization ----------

@pytest.mark.parametrize("raw,canonical", [
    ("http://Evil.example.com:80/ws/", "evil.example.com/ws"),
    ("https://C2.Тест.ru:443", "c2.xn--e1aybc.ru"),  # IDN → punycode (idna codec)
    ("10.0.0.1", "10.0.0.1"),
    ("Evil.COM", "evil.com"),
    ("evil.example.com:8080/path", "evil.example.com:8080/path"),  # non-default port kept
])
def test_normalize_ioc(raw, canonical):
    assert ak.normalize_ioc(raw) == canonical


# ---------- key schema ----------

def _s1_key(**over):
    k = {"stratum": "S1", "family": "vidar",
         "c2": ["http://evil.com/ws"], "mutex": ["M1"],
         "persistence": ["run-key"], "injection": ["process-hollowing"],
         "crypto": ["rc4"], "attck": ["T1071"],
         "config_format": "json",
         "pqs": [{"pq_id": "PQ1", "question": "family?",
                  "expected": "vidar", "matcher": "exact"}]}
    k.update(over)
    return k


def test_valid_s1_key():
    assert ak.validate_key(_s1_key()) == []


def test_missing_required_field():
    k = _s1_key()
    del k["family"]
    assert any("family" in v for v in ak.validate_key(k))


def test_s3_schema_fields():
    k = {"stratum": "S3", "packer_family": "secneo",
         "dex_recoverable": True, "native_entry": ["libjiagu.so"],
         "protections": ["vmp"], "core_functions": ["init"],
         "pqs": [{"pq_id": "PQ1", "question": "packer?",
                  "expected": "secneo", "matcher": "exact"}]}
    assert ak.validate_key(k) == []
    bad = dict(k)
    del bad["dex_recoverable"]
    assert any("dex_recoverable" in v for v in ak.validate_key(bad))


def test_bad_matcher_rejected():
    k = _s1_key()
    k["pqs"][0]["matcher"] = "vibes"
    assert any("matcher" in v for v in ak.validate_key(k))


def test_pq_missing_expected_rejected():
    k = _s1_key()
    del k["pqs"][0]["expected"]
    assert any("expected" in v for v in ak.validate_key(k))


# ---------- matchers ----------

def test_matcher_exact():
    assert ak.match("vidar", "vidar", "exact") is True
    assert ak.match("Wingo", "wingo", "exact") is False


def test_matcher_set_subset():
    # expected IOC set must be covered by the analyst's answer set
    assert ak.match(["evil.com", "10.0.0.1", "extra.com"],
                    ["evil.com", "10.0.0.1"], "set-subset") is True
    assert ak.match(["evil.com"], ["evil.com", "10.0.0.1"],
                    "set-subset") is False


def test_matcher_normalized_ioc():
    assert ak.match("http://Evil.com:80/", "evil.com", "normalized-ioc") is True


def test_matcher_attck_id():
    assert ak.match("t1071", "T1071", "attck-id") is True
    assert ak.match("T1059", "T1071", "attck-id") is False


# ---------- leak prevention ----------

def test_task_spec_pqs_never_carry_expected():
    spec = ak.task_spec_pqs(_s1_key())
    assert spec == [{"pq_id": "PQ1", "question": "family?"}]
    assert all("expected" not in row for row in spec)
