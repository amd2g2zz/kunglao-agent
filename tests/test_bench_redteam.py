# -*- coding: utf-8 -*-
"""B6 (#823): bench_redteam — L2 arm-blind red-team pipeline (divergent
PQs only). The module prepares blind briefs and merges verdicts; the
actual dispatch (kunglao-redteam agent) happens at experiment time.
"""

import bench_redteam as br


def test_divergent_items_extracted():
    l1 = {"per_pq": {"PQ1": True, "PQ2": False, "PQ3": True}}
    claimed = {"PQ1": True, "PQ2": True, "PQ3": True}
    div = br.divergent_items(l1, claimed)
    assert div == ["PQ2"]


def test_no_divergence_no_dispatch():
    l1 = {"per_pq": {"PQ1": True, "PQ2": True}}
    assert br.divergent_items(l1, {"PQ1": True, "PQ2": True}) == []


def test_blind_brief_carries_no_arm_or_sample():
    brief = br.build_task_brief(
        opaque_id="run-abc123", pq_ids=["PQ1", "PQ2"],
        questions={"PQ1": "family?", "PQ2": "c2?"},
        answers={"PQ1": "vidar", "PQ2": "evil.com"})
    text = str(brief)
    assert "run-abc123" in text
    assert "N-arm" not in text and "O-arm" not in text
    assert '"arm"' not in text and "sample" not in text
    assert brief["pqs"][0] == {"pq_id": "PQ1", "question": "family?",
                               "answer": "vidar"}


def test_merge_redteam_overrides_l1():
    l1 = {"per_pq": {"PQ1": True, "PQ2": False}, "success": False,
          "partial_score": 0.5}
    merged = br.merge_verdicts(l1, {"PQ2": True})
    assert merged["per_pq"] == {"PQ1": True, "PQ2": True}
    assert merged["success"] is True
    assert merged["partial_score"] == 1.0
    assert merged["l2_overrides"] == {"PQ2": True}


def test_stub_roundtrip_synthetic_fixture():
    # dispatch → write-back → merge, with a stub reviewer callable
    l1 = {"per_pq": {"PQ1": True, "PQ2": False}, "success": False,
          "partial_score": 0.5}
    div = br.divergent_items(l1, {"PQ1": True, "PQ2": True})
    brief = br.build_task_brief("run-x", div,
                                {"PQ2": "packer?"}, {"PQ2": "secneo"})
    stub_verdicts = br.dispatch_stub(brief)  # stub: confirm the claim side
    merged = br.merge_verdicts(l1, stub_verdicts)
    assert merged["success"] is True
