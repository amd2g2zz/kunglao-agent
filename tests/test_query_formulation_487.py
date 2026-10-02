# -*- coding: utf-8 -*-
"""tests for query formulation (issue #487) — scripts/query_formulation.py.

The flow-gap fix under test: before any retrieval, the distillation act
ENUMERATES AND SUMMARIZES the problem from structured workspace state
(die/apkid evidence + the obstacle registry + the trigger), retrieves PER
FACET over the local re-library, and records the coverage matrix with the
empty-facet disambiguation (ONE reformulation, then corpus-lack).

Pinned here:
  - the problem-representation schema (facets + provenance, 3-5, closed
    kinds, evidence-bounded);
  - per-facet retrieval mechanics (normalization, word boundaries, the
    half-ceiling hit rule, top-k ranking, facet independence);
  - both disambiguation paths (reformulated-hit / corpus-lack) + the
    exactly-one-retry bound;
  - the fixture comparison: good formulation beats fragment queries on
    the same corpus (exact counts — the regression pin);
  - host wiring: the e2e distill act's prompt + audit row carry the
    formulation/coverage; the production closure stamp carries them;
    fail-open degradation.

Zero real-sample bytes; the fixture corpus lives in
tests/fixtures/query-formulation-487/corpus/ (6 synthetic cards).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CORPUS = ROOT / "tests" / "fixtures" / "query-formulation-487" / "corpus"
for p in (str(SCRIPTS),):
    if p not in sys.path:
        sys.path.insert(0, p)

import online_distill as od  # noqa: E402
import query_formulation as qf  # noqa: E402

TOKEN = "android:sign-recovery"
SAMPLE = "bins/libsign.so"

#: the fixture's relevance ground truth: the three cards a correct
#: retrieval MUST surface for the staged problem (and the fragment
#: query must NOT — that is the whole point of #487).
RELEVANT = {
    "native-algorithm-reproduction.md",
    "unpacking-entropy.md",
    "anti-debug-bypass.md",
}
DECOY_JARGON = "jargon-workflow.md"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def stage_rich_ws(tmp_path: Path) -> Path:
    """The staged problem workspace: marker + probe evidence + one
    obstacle row (hand-written valid obstacle/1 — read() revalidates
    structure only, so no probe-marker artifact is needed here)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "bins").mkdir()
    (ws / "bins" / "libsign.so").write_bytes(b"\x7fELF fixture bytes")
    (ws / "runs" / "worker-status-C-004.md").write_text(
        "# worker status\nstatus: BLOCKED\n"
        f"shelf-miss: {TOKEN} sample={SAMPLE}\n", encoding="utf-8")
    (ws / "evidence").mkdir()
    (ws / "evidence" / "apkid.json").write_text(json.dumps({
        "tool": "apkid", "status": "ok", "findings": [],
        "summary": {"packer": ["aplib"], "obfuscator": [],
                    "anti_analysis": ["anti_debug"], "compiler": [],
                    "total": 2}}), encoding="utf-8")
    (ws / "evidence" / "die.json").write_text(json.dumps({
        "derived": {"language": None},
        "call_errors": {"binwalk": "timeout after 30s"}}),
        encoding="utf-8")
    (ws / "runs" / "obstacles").mkdir()
    (ws / "runs" / "obstacles" / "OBS-001.json").write_text(json.dumps({
        "schema": "obstacle/1", "id": "OBS-001",
        "kind": "encryption_layer",
        "cause": "libsign.so opaque 32-byte digest no standard match",
        "evidence_path": "evidence/probe-out.txt",
        "method_family": "native:emulation",
        "ts": "2026-10-02T00:00:00Z"}), encoding="utf-8")
    return ws


def rich_trigger() -> od.Trigger:
    return od.Trigger("shelf-miss", TOKEN, SAMPLE,
                      "runs/worker-status-C-004.md")


def facet_of(formulation: dict, kind: str, face: str | None = None):
    """The (first) facet with the kind/face — None when absent."""
    for f in formulation["facets"]:
        if f["kind"] == kind and f.get("face") == face:
            return f
    return None


def hit_paths(coverage: dict) -> set[str]:
    out: set[str] = set()
    for f in coverage["facets"]:
        out.update(h["path"] for h in f["hits"])
    return out


def verdicts(coverage: dict) -> list[str]:
    return [f["verdict"] for f in coverage["facets"]]


# ---------------------------------------------------------------------------
# the problem-representation schema
# ---------------------------------------------------------------------------


class TestFormulateProblem:
    def test_schema_and_facet_bounds(self, tmp_path):
        doc = qf.formulate_problem(stage_rich_ws(tmp_path), rich_trigger())
        assert doc["schema"] == qf.SCHEMA
        assert 3 <= len(doc["facets"]) <= 5
        assert all(f["kind"] in qf.FACET_KINDS for f in doc["facets"])

    def test_rich_environment_yields_all_five_facets(self, tmp_path):
        doc = qf.formulate_problem(stage_rich_ws(tmp_path), rich_trigger())
        kinds = [(f["kind"], f.get("face")) for f in doc["facets"]]
        assert kinds == [("format_family", None), ("technique", None),
                         ("tool", None),
                         ("error_signature", "obstacle"),
                         ("error_signature", "probe")]

    def test_facet_terms_carry_provenance(self, tmp_path):
        doc = qf.formulate_problem(stage_rich_ws(tmp_path), rich_trigger())
        for f in doc["facets"]:
            assert 1 <= len(f["terms"]) <= 6
            assert f["query"] == " ".join(f["terms"])
            prov_terms = {p["term"] for p in f["provenance"]}
            assert set(f["terms"]) <= prov_terms, (
                f"a term without provenance is fabrication: {f}")
            for p in f["provenance"]:
                assert p["source"] and p["value"]

    def test_format_terms_from_packer_and_suffix(self, tmp_path):
        doc = qf.formulate_problem(stage_rich_ws(tmp_path), rich_trigger())
        fmt = facet_of(doc, "format_family")
        assert "aplib" in fmt["terms"]          # apkid summary.packer
        assert "native library" in fmt["terms"]  # .so suffix map
        srcs = {p["term"]: p["source"] for p in fmt["provenance"]}
        assert "apkid" in srcs["aplib"]
        assert "sample" in srcs["native library"] or \
            "trigger" in srcs["native library"]

    def test_technique_terms_from_anti_analysis_and_obstacle_kind(
            self, tmp_path):
        doc = qf.formulate_problem(stage_rich_ws(tmp_path), rich_trigger())
        tech = facet_of(doc, "technique")
        assert "anti debug" in tech["terms"]    # anti_debug rule, split
        assert "encryption" in tech["terms"]    # encryption_layer map

    def test_tool_terms_from_token_and_method_family(self, tmp_path):
        doc = qf.formulate_problem(stage_rich_ws(tmp_path), rich_trigger())
        tool = facet_of(doc, "tool")
        assert "android" in tool["terms"]
        assert "native emulation" in tool["terms"]  # method_family

    def test_error_facets_from_cause_and_call_errors(self, tmp_path):
        doc = qf.formulate_problem(stage_rich_ws(tmp_path), rich_trigger())
        obst = facet_of(doc, "error_signature", "obstacle")
        assert "digest" in obst["terms"] and "opaque" in obst["terms"]
        probe = facet_of(doc, "error_signature", "probe")
        assert "binwalk" in probe["terms"]

    def test_thin_workspace_still_yields_three_standing_facets(
            self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "worker-status-C-001.md").write_text(
            f"status: BLOCKED\nshelf-miss: {TOKEN}\n", encoding="utf-8")
        doc = qf.formulate_problem(ws, od.Trigger(
            "shelf-miss", TOKEN, None, "runs/worker-status-C-001.md"))
        kinds = [f["kind"] for f in doc["facets"]]
        assert kinds == ["format_family", "technique", "tool"]
        fmt = facet_of(doc, "format_family")
        assert fmt["terms"], "format facet falls back, never empty"
        tech = facet_of(doc, "technique")
        assert tech["terms"], "technique falls back to token components"

    def test_format_unknown_trigger_adds_identification_terms(
            self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        doc = qf.formulate_problem(ws, od.Trigger(
            "format-unknown", "format:unknown:evidence/die.json", None,
            "evidence/die.json"))
        fmt = facet_of(doc, "format_family")
        assert any(t in fmt["terms"] for t in
                   ("unknown format", "file identification", "entropy"))

    def test_corrupt_evidence_is_no_signal_not_a_crash(self, tmp_path):
        ws = stage_rich_ws(tmp_path)
        (ws / "evidence" / "apkid.json").write_text("{not json",
                                                    encoding="utf-8")
        doc = qf.formulate_problem(ws, rich_trigger())
        assert 3 <= len(doc["facets"]) <= 5


# ---------------------------------------------------------------------------
# per-facet retrieval mechanics
# ---------------------------------------------------------------------------


class TestRetrievalMechanics:
    def _mini(self, tmp_path, name: str, text: str) -> Path:
        corpus = tmp_path / "corpus"
        corpus.mkdir(exist_ok=True)
        (corpus / name).write_text(text, encoding="utf-8")
        return corpus

    def _one_facet(self, terms):
        return {"facets": [{"kind": "tool", "face": None,
                            "terms": list(terms),
                            "query": " ".join(terms), "provenance": []}]}

    def test_normalization_hyphen_underscore_equivalence(self, tmp_path):
        corpus = self._mini(tmp_path, "card.md",
                            "anti-analysis sha-256 anti_debug")
        cov = qf.retrieve_facets(corpus, self._one_facet(
            ["anti analysis", "sha 256", "anti debug"]))
        assert cov["facets"][0]["verdict"] == "hit"
        matched = set(cov["facets"][0]["hits"][0]["matched"])
        assert matched == {"anti analysis", "sha 256", "anti debug"}

    def test_word_boundary_blocks_substring(self, tmp_path):
        corpus = self._mini(tmp_path, "card.md", "signature verification")
        cov = qf.retrieve_facets(corpus, self._one_facet(
            ["sign", "verification", "signature forged"]))
        # sign != signature (boundary); 1 of 3 < half-ceiling 2 -> miss
        assert cov["facets"][0]["verdict"] in ("corpus-lack",)
        assert cov["facets"][0]["hits"] == []

    def test_half_ceiling_hit_rule(self, tmp_path):
        corpus = self._mini(tmp_path, "card.md", "alpha beta gamma")
        # 2-term facet: ceiling(2/2)=1 -> one match hits
        cov = qf.retrieve_facets(corpus, self._one_facet(["alpha", "zeta"]))
        assert cov["facets"][0]["verdict"] == "hit"
        # 4-term facet: ceiling(4/2)=2 -> one match misses
        cov = qf.retrieve_facets(corpus, self._one_facet(
            ["alpha", "zeta", "eta", "theta"]))
        assert cov["facets"][0]["verdict"] == "corpus-lack"

    def test_single_term_facet_hits_on_one(self, tmp_path):
        corpus = self._mini(tmp_path, "card.md", "the gamma ray burst")
        cov = qf.retrieve_facets(corpus, self._one_facet(["gamma"]))
        assert cov["facets"][0]["verdict"] == "hit"

    def test_yaml_cards_are_corpus(self, tmp_path):
        corpus = self._mini(tmp_path, "seeds.yaml",
                            "name: arm-kdf\nconstants: movz movk\n")
        cov = qf.retrieve_facets(corpus, self._one_facet(
            ["arm kdf", "movz"]))
        assert cov["facets"][0]["verdict"] == "hit"

    def test_top_k_cap_and_ranking(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        for i in range(7):
            (corpus / f"card-{i:02d}.md").write_text(
                "alpha beta gamma" + (" delta" if i < 3 else ""),
                encoding="utf-8")
        cov = qf.retrieve_facets(corpus, self._one_facet(
            ["alpha", "beta", "gamma", "delta"]))
        hits = cov["facets"][0]["hits"]
        assert len(hits) == 5, "top-k cap"
        assert hits[0]["path"] == "card-00.md" and \
            hits[0]["score"] == 4, "score desc, path asc"
        assert all(h["score"] >= 2 for h in hits)

    def test_facets_are_independent(self, tmp_path):
        corpus = self._mini(tmp_path, "card.md", "alpha beta gamma")
        form = {"facets": [
            {"kind": "tool", "face": None, "terms": ["alpha", "beta"],
             "query": "alpha beta", "provenance": []},
            {"kind": "technique", "face": None, "terms": ["gamma"],
             "query": "gamma", "provenance": []}]}
        cov = qf.retrieve_facets(corpus, form)
        assert [f["verdict"] for f in cov["facets"]] == ["hit", "hit"]
        assert cov["facets"][0]["hits"][0]["path"] == "card.md"
        assert cov["facets"][1]["hits"][0]["path"] == "card.md"

    def test_coverage_schema_and_summary(self, tmp_path):
        corpus = self._mini(tmp_path, "card.md", "alpha beta gamma")
        cov = qf.retrieve_facets(corpus, self._one_facet(["alpha", "beta"]))
        assert cov["schema"] == qf.COVERAGE_SCHEMA
        assert cov["corpus"]
        s = cov["summary"]
        assert s["facets"] == 1 and s["hits"] == 1
        assert s["corpus_lack"] == 0 and s["reformulated_hits"] == 0
        assert qf.coverage_summary(cov) == s


# ---------------------------------------------------------------------------
# empty-facet disambiguation
# ---------------------------------------------------------------------------


class TestDisambiguation:
    def _facet(self, terms, prov_value):
        return {"facets": [{"kind": "tool", "face": None,
                            "terms": list(terms),
                            "query": " ".join(terms),
                            "provenance": [{"source": "test#prov",
                                            "value": prov_value,
                                            "term": terms[0]}]}]}

    def test_reformulated_hit_recovers_a_bad_query(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "cert.md").write_text(
            "x509 sig verify pinning chain", encoding="utf-8")
        cov = qf.retrieve_facets(
            corpus, self._facet(["signature verification"], "sig_verify_x509"))
        f = cov["facets"][0]
        assert f["verdict"] == "reformulated-hit"
        assert f["reformulated"] is True
        assert f["reformulated_query"]
        assert f["hits"] and f["hits"][0]["path"] == "cert.md"
        assert cov["summary"]["reformulated_hits"] == 1

    def test_retry_fails_then_corpus_lack(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "card.md").write_text("unrelated content",
                                        encoding="utf-8")
        cov = qf.retrieve_facets(
            corpus, self._facet(["obfuscation cascade"], "ollvm_flatten"))
        f = cov["facets"][0]
        assert f["verdict"] == "corpus-lack"
        assert f["reformulated"] is True, "one retry happened"
        assert f["reformulated_query"], "the retry is recorded"
        assert cov["summary"]["corpus_lack"] == 1

    def test_no_rewordable_material_skips_the_retry(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "card.md").write_text("unrelated content",
                                        encoding="utf-8")
        # single-word terms whose provenance tokenizes to the same
        # words: the retry vocabulary is EXHAUSTED, not reworded
        cov = qf.retrieve_facets(
            corpus, self._facet(["gamma"], "gamma"))
        f = cov["facets"][0]
        assert f["verdict"] == "corpus-lack"
        assert f["reformulated"] is False, \
            "no new vocabulary -> no fake retry"
        assert "reformulated_query" not in f

    def test_exactly_one_reformulation(self, tmp_path):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "card.md").write_text("nothing here", encoding="utf-8")
        form = self._facet(["obfuscation cascade"], "ollvm_flatten")
        cov = qf.retrieve_facets(corpus, form)
        f = cov["facets"][0]
        # the retry vocabulary is EXACTLY the provenance tokens minus the
        # original terms (the rewording source is pinned, not just present)
        assert f["reformulated"] is True
        assert f["reformulated_query"] == "ollvm flatten"
        assert f["verdict"] == "corpus-lack"
        # the verdict vocabulary is closed: one retry, then a verdict
        assert f["verdict"] in ("hit", "reformulated-hit", "corpus-lack")


# ---------------------------------------------------------------------------
# THE fixture comparison: good formulation beats fragment queries
# ---------------------------------------------------------------------------


class TestFormulationBeatsFragments:
    def test_relevant_card_coverage_formulation_vs_fragment(self, tmp_path):
        ws = stage_rich_ws(tmp_path)
        form = qf.formulate_problem(ws, rich_trigger())
        cov = qf.retrieve_facets(CORPUS, form)
        # every relevant card is retrieved by some facet (3/3)
        got = hit_paths(cov)
        assert RELEVANT <= got, (
            f"formulation must cover the relevant cards: "
            f"missing={sorted(RELEVANT - got)}")
        # the fragment baseline (the pre-#487 query: the raw trigger
        # fragment) covers NONE of them
        frag_terms = qf.fragment_baseline_terms(TOKEN)
        frag_cov = qf.retrieve_facets(CORPUS, {"facets": [{
            "kind": "tool", "face": None, "terms": frag_terms,
            "query": " ".join(frag_terms), "provenance": []}]})
        frag_got = hit_paths(frag_cov)
        assert frag_got == {DECOY_JARGON}, (
            "the fragment query only ever finds the jargon decoy")
        assert not (RELEVANT & frag_got)
        # exact counts pinned (the regression pin, not a threshold)
        assert len(RELEVANT & got) == 3
        assert len(RELEVANT & frag_got) == 0

    def test_fixture_verdicts_pinned(self, tmp_path):
        ws = stage_rich_ws(tmp_path)
        form = qf.formulate_problem(ws, rich_trigger())
        cov = qf.retrieve_facets(CORPUS, form)
        assert verdicts(cov) == ["hit", "hit", "hit",
                                 "corpus-lack", "corpus-lack"]
        fmt = cov["facets"][0]
        assert {h["path"] for h in fmt["hits"]} == {
            "native-algorithm-reproduction.md", "unpacking-entropy.md"}
        tech = cov["facets"][1]
        assert {h["path"] for h in tech["hits"]} == {"anti-debug-bypass.md"}
        assert cov["summary"] == {"facets": 5, "hits": 3,
                                  "reformulated_hits": 0,
                                  "corpus_lack": 2}


# ---------------------------------------------------------------------------
# host convenience + CLI
# ---------------------------------------------------------------------------


class TestHostFaces:
    def test_formulate_and_retrieve_over_the_real_relibrary(self, tmp_path):
        ws = stage_rich_ws(tmp_path)
        out = qf.formulate_and_retrieve(ws, rich_trigger(), repo=ROOT)
        assert out["formulation"]["schema"] == qf.SCHEMA
        assert out["coverage"]["schema"] == qf.COVERAGE_SCHEMA
        assert out["coverage"]["facets"], "real corpus, real verdicts"

    def test_missing_corpus_degrades_loudly_not_wrong(self, tmp_path):
        ws = stage_rich_ws(tmp_path)
        out = qf.formulate_and_retrieve(ws, rich_trigger(),
                                        repo=tmp_path / "nowhere")
        assert out["coverage"].get("error") == "corpus-missing"
        assert out["coverage"]["facets"] == []

    def test_cli_formulate_reads_the_stamp(self, tmp_path, capsys):
        ws = stage_rich_ws(tmp_path)
        od.stamp_trigger(ws, [rich_trigger()])
        rc = qf.main([str(ws), "--formulate", "--corpus", str(CORPUS)])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["formulation"]["facets"]
        assert out["coverage"]["summary"]["facets"] == 5

    def test_cli_formulate_without_stamp_is_a_named_error(
            self, tmp_path, capsys):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        rc = qf.main([str(ws), "--formulate"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert out.get("reason")


# ---------------------------------------------------------------------------
# engine + production wiring
# ---------------------------------------------------------------------------


class TestEngineWiring:
    def test_formulate_for_trigger_returns_both_docs(self, tmp_path):
        ws = stage_rich_ws(tmp_path)
        got = od.formulate_for_trigger(ws, rich_trigger())
        assert got and got["formulation"]["facets"] \
            and got["coverage"]["facets"]

    def test_stamp_trigger_carries_formulation(self, tmp_path):
        ws = stage_rich_ws(tmp_path)
        doc = od.formulate_for_trigger(ws, rich_trigger())
        assert od.stamp_trigger(ws, [rich_trigger()], formulation=doc)
        stamp = json.loads(
            (ws / "runs" / "distill-trigger.json").read_text("utf-8"))
        assert stamp["triggers"]
        assert stamp["formulation"]["facets"]
        assert stamp["coverage"]["summary"]

    def test_scan_cli_stamps_the_formulation(self, tmp_path, capsys):
        ws = stage_rich_ws(tmp_path)
        capsys.readouterr()
        assert od.main([str(ws), "--scan"]) == 0
        stamp = json.loads(
            (ws / "runs" / "distill-trigger.json").read_text("utf-8"))
        assert stamp["formulation"]["facets"]
        assert stamp["coverage"]["summary"]

    def test_formulation_failure_is_fail_open(self, tmp_path, monkeypatch):
        ws = stage_rich_ws(tmp_path)
        monkeypatch.setattr(
            qf, "formulate_and_retrieve",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert od.formulate_for_trigger(ws, rich_trigger()) is None
        # the stamp still lands, unformulated (the pre-#487 shape)
        assert od.stamp_trigger(ws, [rich_trigger()],
                                formulation=None)
        stamp = json.loads(
            (ws / "runs" / "distill-trigger.json").read_text("utf-8"))
        assert "formulation" not in stamp


class TestProductionClosure:
    def _payload(self, ws: Path) -> dict:
        return {"cwd": str(ws), "session_id": "s1",
                "transcript_path": str(ws / "t.jsonl")}

    def test_closure_stamp_carries_formulation(self, tmp_path, capsys):
        sys.path.insert(0, str(ROOT / "hooks"))
        import round_closure  # noqa: PLC0415
        ws = stage_rich_ws(tmp_path)
        (ws / ".hook_state.json").write_text("{}", encoding="utf-8")
        rc = round_closure.main_with_payload(self._payload(ws))
        capsys.readouterr()
        assert rc == 0
        stamp = json.loads(
            (ws / "runs" / "distill-trigger.json").read_text("utf-8"))
        assert stamp["formulation"]["facets"]
        assert stamp["coverage"]["summary"]["facets"] == 5


class TestSkillDocPin:
    def test_skill_doc_documents_the_formulation_step(self):
        doc = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
            encoding="utf-8")
        assert "formulation" in doc.lower()


# ---------------------------------------------------------------------------
# e2e wiring: the distill act starts with formulation
# ---------------------------------------------------------------------------

from e2e import audit, checkpoints, llm_faces, model  # noqa: E402

ANCHORS = {
    "goal_verbatim": "Recover the transform and decode target/blob.bin.",
    "success_criterion": "The decoded plaintext matches the expected digest.",
    "verification_method": "reproduction",
}
DISTILL_FIXTURE = ROOT / "tests" / "fixtures" / "distill-458"


def _mk_ctx(tmp_path: Path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    ev_dir = tmp_path / "ev"
    ev_dir.mkdir(parents=True, exist_ok=True)
    state = model.RunState(
        run_id="r1", unit="qf-fixture", family="smoke",
        repo=str(ROOT), task_dir=str(ROOT / "eval/v1/tasks/smoke"),
        ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
        llm_mode="dry", started_ts="t", started_monotonic=0.0,
        anchors=dict(ANCHORS))
    runner = llm_faces.CommandRunner(ROOT)
    face = llm_faces.face_for("dry", runner, ev_dir)

    class _Clock:
        def monotonic(self) -> float:
            return 0.0

    return checkpoints.RunContext(
        state=state, runner=runner, face=face,
        clock=_Clock(), sleep_fn=lambda _s: None)


def _stage_458(ws: Path) -> None:
    (ws / "bins").mkdir(exist_ok=True)
    (ws / "bins" / "blob.bin").write_bytes(
        (DISTILL_FIXTURE / "sample.blob").read_bytes())
    (ws / "runs" / "worker-status-C-004.md").write_text(
        "# worker status\nstatus: BLOCKED\n"
        "shelf-miss: crypto:decode sample=bins/blob.bin\n",
        encoding="utf-8")


def _audit_rows(ws: Path) -> list[dict]:
    path = audit.audit_path(ws)
    return [json.loads(ln) for ln
            in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestE2EWiring:
    def _prompt_text(self, ctx) -> str:
        prompts = sorted(Path(ctx.state.evidence_dir).glob(
            "dispatch-prompt-attempt-*.md"))
        assert prompts, "the distill dispatch prompt must be staged"
        return prompts[-1].read_text(encoding="utf-8")

    def test_prompt_and_audit_carry_formulation(self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        _stage_458(ctx.ws)
        detail: dict = {}
        checkpoints._maybe_distill(ctx, detail)
        # the act ran to landing (formulation must not disturb it)
        assert (ctx.ws / "tools-local" / "transform-recover.py").is_file()
        # the dispatch prompt carries the formulation + coverage
        text = self._prompt_text(ctx)
        assert "Problem formulation" in text
        assert "facets" in text and "coverage" in text
        # the distill_result audit row's detail carries the matrix
        rows = [r for r in _audit_rows(ctx.ws)
                if r["action"] == "distill_result"]
        assert rows
        result_detail = json.loads(rows[-1]["detail"])
        assert result_detail["coverage"]["facets"]
        # the tick detail carries formulation + coverage (design: both)
        assert detail["distill"][0].get("formulation")
        assert detail["distill"][0].get("coverage", {}).get("facets")

    def test_formulation_failure_degrades_fail_open(self, tmp_path,
                                                    monkeypatch):
        monkeypatch.setattr(
            qf, "formulate_and_retrieve",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        ctx = _mk_ctx(tmp_path)
        _stage_458(ctx.ws)
        detail: dict = {}
        checkpoints._maybe_distill(ctx, detail)
        # the act still lands (the capability never blocks the loop)
        assert (ctx.ws / "tools-local" / "transform-recover.py").is_file()
        # the prompt keeps the pre-#487 shape (no formulation section)
        assert "Problem formulation" not in self._prompt_text(ctx)
        rows = [r for r in _audit_rows(ctx.ws)
                if r["action"] == "distill_result"]
        result_detail = json.loads(rows[-1]["detail"])
        assert "coverage" not in result_detail
