# -*- coding: utf-8 -*-
"""B6 (#823): bench_redteam — L2 arm-blind red-team pipeline (divergent
PQs only). The module prepares blind briefs and merges verdicts; the
actual dispatch (kunglao-redteam agent) happens at experiment time.
"""

import bench_redteam as br


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
