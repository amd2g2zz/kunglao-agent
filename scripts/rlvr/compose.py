# -*- coding: utf-8 -*-
"""compose.py — the strategy compose single-point (kernel W2-T3, issue 431).

The learned state becomes words the LLM sees. Per decision event ONE
round-strategy object is composed (schema ``round-strategy/1``) into
``runs/round-strategy/tick-NNNN.yaml`` carrying the four issue-429 outlets:

    dispatch:   method_lead / anti_hints / budget_hint
    loop:       monitor_focus / ping_policy / stall_rules
    hooks:      cards to inject (card ids; consumers read
                runs/strategy-cards/<id>.yaml)
    amendments: parameter amendments with evidence_refs (mechanical v1
                emits []; the entry shape is schema-reserved)

Determinism wall: no model call, no invented sentences. Every sentence is
a template slot filled from named ledger rows; card text cites its
backing_refs inline at render time. Same (ledger, cards, store view) ->
byte-identical rendered sections -> identical ``content_hash`` (sha256
over the canonical rendered sections — the consumers' dedup key). The
consumer seam projection (``runs/round-strategy.json``, issue 462 W2)
is derived deterministically from the same object, so both write faces
are reproducible from workspace state alone.

Card library (schema ``card/1``): cards accumulate from settlement
events. Sources in v1: dead_path from settled task FAIL rows (the
issue-391 gap-note family), success_recipe from settled positive-band
task rows, exogenous_pitfall mint-callable (the issue-421 classifier
joins as a source later). Cards fade, never delete: staleness and
supersession remove a card from INJECTION while its file stays on disk.

Mint gate (owner ruling 2026-09-28): a whitespace-normalized verbatim
run of >= MINT_MAX_VERBATIM_WORDS words between card text and any SINGLE
backing row's sample fields rejects the mint. Methodology transcription
is legal; raw splicing is not.

Segment discipline: card text rides the dynamic strategy segments only.
The constitution segment is permanently card-free — pinned by
assert_cards_allowed plus the validator's exact-section-set rule.

Store seam: ALL learned arithmetic (DTS-sampled method lead, γ decay
weights, cell population) belongs to the posterior store (issue 428,
parallel work stream). compose sees it only through the
StrategyStore protocol; since issue 462 W3 the seam is REAL —
``load_store`` returns ``rlvr.strategy_store.PosteriorStrategyStore``
over the landed q_cells/posteriors faces, and a store failure
propagates loudly (compose is the decision single-point: fail-closed,
never a silent fake policy — the former silent IdentityStore degrade is
closed; IdentityStore survives as an explicit test/experiment stub only).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Protocol, Sequence

import yaml

from rlvr import ledger as rl  # the package faces (issue 420 Phase 2)
from rlvr import state as state_signature

from _common import read_yaml

SCHEMA = "round-strategy/1"
CARD_SCHEMA = "card/1"
STRATEGY_DIR_REL = PurePosixPath("runs") / "round-strategy"
CARDS_DIR_REL = PurePosixPath("runs") / "strategy-cards"
# the consumer seam (issue 462 W2): the derived projection of the
# strategy IN FORCE, in the exact shape scripts/strategy_sections.py
# reads ({schema, round, sections:[{title, body}]}). The tick files
# stay the versioned ledger (reconstructability); this file is the
# broadcast face the loop prompt renders.
SEAM_REL = PurePosixPath("runs") / "round-strategy.json"

CARD_KINDS = ("success_recipe", "dead_path", "exogenous_pitfall")
ANTI_HINT_KINDS = ("dead_path", "exogenous_pitfall")

SEGMENT_CONSTITUTION = "constitution"
SEGMENT_STRATEGY = "strategy"

# evidence threshold: below this many settled rows in the cell, inject
# NOTHING (cold start is silence, not noise)
DEFAULT_N_MIN = 2
# injection budget: at most this many cards ride one strategy object
DEFAULT_TOP_K = 4
# settlements a card stays fresh without re-derivation
DEFAULT_EVIDENCE_WINDOW = 20
# mint gate mechanical criterion (owner ruling 2026-09-28)
MINT_MAX_VERBATIM_WORDS = 12
# bounded scan per sample field (gate soundness note: a longer field is
# scanned to this word bound; the bound is far beyond any legal overlap
# a twelve-word run needs to hide behind in practice)
MAX_SAMPLE_FIELD_WORDS = 20_000

PING_POLICY = "event_driven_guardian"
STALL_RULES = (
    "flat_progress_two_consecutive_ticks_park_candidate",
    "no_verified_artifact_within_closure_budget_force_expiry",
)

_CARD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-(success_recipe|dead_path|exogenous_pitfall)-[0-9a-f]{12}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f][0-9a-f-]{7,}$")
_HEX12_RE = re.compile(r"^[0-9a-f]{12}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

from kunglao_log import warn  # canonical warn: ONE implementation


class MintGateError(ValueError):
    """Card text splices raw sample bytes from a backing row."""


class SegmentError(ValueError):
    """Card content routed into a barred prompt segment."""


# ------------------------------------------------------------ store seam

class StrategyStore(Protocol):
    """The learned-state seam. compose owns templates + scheduling; the
    store owns ALL learned arithmetic (DTS sampling, γ decay,
    cell population). Implementations come from the posterior store
    (issue 428)."""

    def method_lead(self, state_fingerprint: str) -> str | None: ...

    def decayed_weight(self, row_id: str) -> float: ...

    def cell_count(self, state_fingerprint: str) -> int | None: ...


class IdentityStore:
    """The no-store fallback: no learned lead, unit decay weights, and a
    None cell count (compose falls back to the settled-ledger total)."""

    def method_lead(self, state_fingerprint: str) -> str | None:
        return None

    def decayed_weight(self, row_id: str) -> float:
        return 1.0

    def cell_count(self, state_fingerprint: str) -> int | None:
        return None


def load_store(ws) -> StrategyStore:
    """THE real store seam (issue 462 W3): the PosteriorStrategyStore
    over the landed learned-state faces (rlvr.q_cells + rlvr.posteriors
    + the settled ledger). The former silent IdentityStore degrade is
    CLOSED — any failure propagates loudly (compose is the decision
    single-point: fail-closed, never a silent fake policy)."""
    from rlvr.strategy_store import PosteriorStrategyStore  # noqa: PLC0415
    return PosteriorStrategyStore(Path(ws))


# ------------------------------------------------------------- canonical

def canonical_json(obj) -> str:
    """Canonical JSON: sorted keys, tight separators, unicode kept."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def strategy_content_hash(sections: dict) -> str:
    """sha256 over the canonical rendered sections — the dedup key.
    Tick and wall-clock are deliberately outside: two ticks composing
    identical sections share one hash and consumers skip."""
    return hashlib.sha256(
        canonical_json(sections).encode("utf-8")).hexdigest()


# ------------------------------------------------------------- mint gate

def _norm_words(text: str) -> list[str]:
    """Whitespace-normalized word tokens (the ruling's normalization)."""
    return re.findall(r"\S+", str(text or ""))


def row_sample_fields(row: dict) -> list[str]:
    """The raw-evidence faces of one ledger row: its non-advisory machine
    signal values (advisory carriers are derived, not raw — the same
    exclusion the gap-note builder applies)."""
    out: list[str] = []
    for sig in row.get("signals") or []:
        if not isinstance(sig, dict) or sig.get("advisory"):
            continue
        value = sig.get("value")
        if isinstance(value, (dict, list)):
            out.append(canonical_json(value))
        else:
            out.append(str(value))
    return out


def longest_common_word_run(a: Sequence[str], b: Sequence[str]) -> int:
    """Longest contiguous verbatim word run between two token lists."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def mint_gate_violation(text: str, rows: Sequence[dict]) -> str | None:
    """The offending row id when card text carries a verbatim run of
    MINT_MAX_VERBATIM_WORDS or more words from any SINGLE row's sample
    fields; None when the text is methodology-clean."""
    text_words = _norm_words(text)
    if not text_words:
        return None
    for row in rows:
        for field in row_sample_fields(row):
            words = _norm_words(field)
            if len(words) > MAX_SAMPLE_FIELD_WORDS:
                warn("mint_gate",
                     f"sample field truncated to {MAX_SAMPLE_FIELD_WORDS} "
                     f"words for the run scan")
                words = words[:MAX_SAMPLE_FIELD_WORDS]
            if longest_common_word_run(text_words, words) \
                    >= MINT_MAX_VERBATIM_WORDS:
                return str(row.get("rollout_id") or "")
    return None


# ------------------------------------------------------------ card mint

def mint_card(*, kind: str, scope_fingerprint: str, method_family: str,
              text: str, backing_refs: Sequence[str], minted_tick: int,
              minted_settlements: int,
              evidence_window: int = DEFAULT_EVIDENCE_WINDOW,
              superseded_by: str | None = None,
              backing_rows: Sequence[dict] | None = None) -> dict:
    """One card/1 document. Content-addressed: id and content_hash cover
    the semantic core (kind, scope, family, text, backing refs) —
    lifecycle fields (minted_tick / minted_settlements / evidence_window
    / superseded_by) live outside the hash so re-derivation and
    supersession never change a card's identity. Raises MintGateError
    when backing_rows is supplied and the text splices raw bytes."""
    if kind not in CARD_KINDS:
        raise ValueError(f"card kind {kind!r} not in {CARD_KINDS}")
    scope_fingerprint = str(scope_fingerprint or "").lower()
    if not _FINGERPRINT_RE.match(scope_fingerprint):
        raise ValueError("scope_fingerprint: hex-ish token of 8+ chars")
    method_family = str(method_family or "").strip()
    if not method_family:
        raise ValueError("method_family: empty")
    text = str(text or "").strip()
    if not text:
        raise ValueError("text: empty")
    refs = sorted({str(r) for r in (backing_refs or []) if str(r).strip()})
    if not refs:
        raise ValueError("backing_refs: empty")
    if backing_rows is not None:
        offender = mint_gate_violation(text, backing_rows)
        if offender:
            raise MintGateError(
                f"text carries a verbatim run of "
                f"{MINT_MAX_VERBATIM_WORDS}+ words from row {offender!r} "
                f"(methodology transcription only; raw splicing illegal)")
    core = {"kind": kind, "scope_fingerprint": scope_fingerprint,
            "method_family": method_family, "text": text,
            "backing_refs": refs}
    digest = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    card = dict(core)
    card["schema"] = CARD_SCHEMA
    card["id"] = f"{scope_fingerprint[:8]}-{kind}-{digest[:12]}"
    card["minted_tick"] = int(minted_tick)
    card["minted_settlements"] = int(minted_settlements)
    card["evidence_window"] = int(evidence_window)
    card["superseded_by"] = superseded_by
    card["content_hash"] = digest
    return card


def _cards_dir(ws: Path) -> Path:
    return ws / CARDS_DIR_REL


def _atomic_write_text(path: Path, text: str) -> None:
    """Atomic text write (writer-unique tmp + os.replace): since #462 W1
    the compose write faces run from the production SubagentStop hook,
    where two workers stopping together spawn concurrent hook processes
    on one workspace — a fixed tmp name would let the two writers
    truncate each other's buffer mid-write and tear the file (the
    two-writer race, demonstrated in review); the unique name makes each
    rename atomic AND writer-isolated. Card/strategy/seam files are
    whole-document replaces, never appends (the ledger keeps its own
    locked append face)."""
    import os  # noqa: PLC0415 — stdlib local, keeps the module import face
    import tempfile  # noqa: PLC0415
    fd, name = tempfile.mkstemp(dir=path.parent,
                                prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        # 0o644 parity with the pre-atomic write_text face (mkstemp
        # creates 0600; same-user consumers are unaffected but a
        # cross-user read face over these artifacts must not regress)
        os.chmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError as exc:  # non-silent: the #275 house rule
                warn("atomic_cleanup",
                     f"{path.name}: tmp {tmp.name} left behind: "
                     f"{type(exc).__name__}: {exc}")


def save_card(ws, card: dict) -> dict:
    """Write (or refresh) one card file. Idempotent: same semantic content
    refreshes the lifecycle fields (the re-derive face — the evidence
    window restarts), identity fields untouched. Returns
    {"written", "refreshed", "path"}."""
    ws = Path(ws)
    path = _cards_dir(ws) / f"{card['id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing, err = read_yaml(path)
        if existing is None:
            warn("save_card", err)
        if isinstance(existing, dict) \
                and existing.get("content_hash") == card["content_hash"]:
            refreshed = dict(existing)
            refreshed["minted_settlements"] = int(card["minted_settlements"])
            refreshed["evidence_window"] = int(card["evidence_window"])
            refreshed["minted_tick"] = int(card["minted_tick"])
            if card.get("superseded_by"):
                refreshed["superseded_by"] = card["superseded_by"]
            _atomic_write_text(
                path, yaml.safe_dump(refreshed, allow_unicode=True,
                                     sort_keys=True))
            return {"written": False, "refreshed": True, "path": path}
    _atomic_write_text(
        path, yaml.safe_dump(card, allow_unicode=True, sort_keys=True))
    return {"written": True, "refreshed": False, "path": path}


def supersede_card(ws, old_id: str, new_id: str) -> bool:
    """Record supersession on the OLD card file (history kept — the file
    stays, only the lifecycle pointer moves). True when applied."""
    path = _cards_dir(Path(ws)) / f"{old_id}.yaml"
    card, err = read_yaml(path)
    if card is None:
        warn("supersede_card", err)
        return False
    if not isinstance(card, dict) or card.get("id") != old_id:
        return False
    card["superseded_by"] = str(new_id)
    _atomic_write_text(path, yaml.safe_dump(card, allow_unicode=True,
                                            sort_keys=True))
    return True


def load_cards(ws) -> list[dict]:
    """All card documents on file, ascending id order. Unreadable files
    are skipped with a warn (the library never blocks composition)."""
    directory = _cards_dir(Path(ws))
    if not directory.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(directory.glob("*.yaml")):
        card, err = read_yaml(path)
        if card is None:
            warn("load_cards", f"{path.name}: {err}")
            continue
        if _CARD_ID_RE.match(str(card.get("id"))):
            out.append(card)
    return out


# ------------------------------------------------- settlement accumulation

def method_family_of_row(row: dict) -> str:
    """The declared method family of a settled row (last
    method_family signal wins); 'any' when the row declares none."""
    family = None
    for sig in row.get("signals") or []:
        if isinstance(sig, dict) \
                and str(sig.get("type") or "") == "method_family":
            family = sig.get("value")
    return str(family).strip() if family and str(family).strip() else "any"


def _card_text(kind: str, family: str, bands: Sequence[str],
               rules: Sequence[str]) -> str:
    """Deterministic template text. Enum tokens only — no row prose is
    ever spliced (the mint gate would reject that anyway)."""
    band_list = ",".join(sorted(set(bands)))
    rule_list = ",".join(sorted(set(rules)))
    if kind == "dead_path":
        return (f"dead path: method family {family} kept settling "
                f"[{band_list}] under [{rule_list}] at this scope; do not "
                f"re-derive this family here without new contradicting "
                f"evidence")
    if kind == "success_recipe":
        return (f"success recipe: method family {family} settled "
                f"[{band_list}] under [{rule_list}] at this scope; prefer "
                f"this family for matching states")
    return (f"exogenous pitfall: environment hazard observed while "
            f"method family {family} settled [{band_list}] at this scope; "
            f"check the cited rows before re-entry")


def refresh_cards(ws, *, tick: int) -> dict:
    """Accumulate cards from settlement events (the issue-429 settlement
    clock feeds the card bank). Groups settled task rows by (kind,
    scope, family): FAIL rows -> dead_path groups, positive-band rows ->
    success_recipe groups. Each group mints ONE template card backed by
    all its rows; a previously hand-minted card for the same group but
    with different content is superseded (v2 replaces v1, history kept);
    identical content refreshes in place (re-derive face). Returns
    {"minted", "refreshed", "superseded", "rejected"}."""
    ws = Path(ws)
    rows = rl.settled(ws, kind="task")
    total = len(rl.settled(ws))
    fp = state_signature.signature_hash(state_signature.snapshot(ws))
    groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        band = str(row.get("band") or "")
        if band in ("SETTLED_RED", "ADVERSE"):
            kind = "dead_path"
        elif band in ("SETTLED_GREEN", "HELPED"):
            kind = "success_recipe"
        else:
            continue  # neutral bands reflect nothing
        key = (kind, method_family_of_row(row))
        entry = groups.setdefault(key, {"refs": [], "bands": [],
                                        "rules": [], "rows": []})
        entry["refs"].append(str(row.get("rollout_id")))
        entry["bands"].append(band)
        rules = (row.get("settlement") or {}).get("rule_id")
        if rules:
            entry["rules"].append(str(rules))
        entry["rows"].append(row)

    out = {"minted": 0, "refreshed": 0, "superseded": 0, "rejected": []}
    by_group: dict[tuple[str, str, str], str] = {}
    for (kind, family), entry in sorted(groups.items()):
        text = _card_text(kind, family, entry["bands"], entry["rules"])
        try:
            card = mint_card(kind=kind, scope_fingerprint=fp,
                             method_family=family, text=text,
                             backing_refs=entry["refs"], minted_tick=tick,
                             minted_settlements=total,
                             backing_rows=entry["rows"])
        except MintGateError as exc:
            out["rejected"].append(f"{kind}/{family}: {exc}")
            warn("refresh_cards", str(exc))
            continue
        result = save_card(ws, card)
        by_group[(kind, fp, family)] = card["id"]
        if result["written"]:
            out["minted"] += 1
        elif result["refreshed"]:
            out["refreshed"] += 1

    # supersession: any live card matching a derived group but carrying a
    # different (hand-written) text is replaced by the derived card
    for card in load_cards(ws):
        key = (str(card.get("kind")), str(card.get("scope_fingerprint")),
               str(card.get("method_family")))
        derived_id = by_group.get(key)
        if derived_id and card["id"] != derived_id \
                and not card.get("superseded_by"):
            if supersede_card(ws, card["id"], derived_id):
                out["superseded"] += 1
    return out


# ------------------------------------------------------------- scheduling

def is_stale(card: dict, settled_total: int) -> bool:
    """True when more than evidence_window settlements passed since the
    card's evidence snapshot (re-derive or fade)."""
    return (int(settled_total) - int(card.get("minted_settlements") or 0)) \
        > int(card.get("evidence_window") or 0)


def card_rank(card: dict, store: StrategyStore) -> float:
    """Gamma-linked retrieval rank: sum of the store's decayed weight
    over the card's backing rows (the statistical face of knowledge
    expiry, made visible in the context layer)."""
    return sum(store.decayed_weight(str(r))
               for r in (card.get("backing_refs") or []))


def schedule_cards(cards: Sequence[dict], store: StrategyStore, *,
                   settled_total: int, top_k: int = DEFAULT_TOP_K
                   ) -> list[dict]:
    """The injection set: live (never superseded), fresh (not stale),
    ranked by decayed backing, bounded by the top-k budget. Deterministic
    tie-break on card id."""
    live = [c for c in cards
            if not c.get("superseded_by")
            and not is_stale(c, settled_total)]
    ranked = sorted(live, key=lambda c: (-card_rank(c, store), str(c["id"])))
    return list(ranked[:max(int(top_k), 0)])


# -------------------------------------------------------------- segments

def assert_cards_allowed(segment: str) -> None:
    """Segment discipline gate: card content is barred from the
    constitution segment (the fixed SessionStart layer). Cards ride the
    dynamic strategy segments only — every render face passes through
    here, so a constitution leak is a raise, never a render."""
    if str(segment) == SEGMENT_CONSTITUTION:
        raise SegmentError(
            "card content is barred from the constitution segment "
            "(cards ride the dynamic strategy segments only)")


def render_card_block(card: dict, segment: str = SEGMENT_STRATEGY) -> str:
    """One attributable card line: kind tag + text + inline ledger
    attribution (refs ride WITH the sentence — provenance is part of the
    rendered content, not a side table)."""
    assert_cards_allowed(segment)
    refs = ", ".join(str(r) for r in (card.get("backing_refs") or []))
    return f"[{card['kind']}] {card['text']} (refs: {refs})"


# ------------------------------------------------------------ validation

def _validate_identity(obj: dict, errors: list[str]) -> None:
    """The provenance header faces."""
    if obj.get("schema") != SCHEMA:
        errors.append(f"schema: expected {SCHEMA!r}")
    tick = obj.get("tick")
    if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
        errors.append("tick: non-negative integer required")
    if not _HEX12_RE.match(str(obj.get("state_fingerprint") or "")):
        errors.append("state_fingerprint: 12-hex required")
    if not _HEX64_RE.match(str(obj.get("content_hash") or "")):
        errors.append("content_hash: 64-hex required")
    if not str(obj.get("ts") or "").strip():
        errors.append("ts: empty")
    refs = obj.get("composed_from")
    if not isinstance(refs, list) \
            or any(not str(r).strip() for r in refs) \
            or list(refs) != sorted(set(str(r) for r in refs)):
        errors.append("composed_from: sorted unique row ids required")


def _validate_dispatch(obj: dict, errors: list[str]) -> None:
    dispatch = obj.get("dispatch")
    keys = {"method_lead", "anti_hints", "budget_hint"}
    if not isinstance(dispatch, dict):
        errors.append("dispatch: mapping required")
        return
    if set(dispatch) != keys:
        errors.append(f"dispatch: keys must be exactly {sorted(keys)}")
        return
    lead = dispatch.get("method_lead")
    if lead is not None and not str(lead).strip():
        errors.append("dispatch.method_lead: null or non-empty string")
    if not isinstance(dispatch.get("anti_hints"), list) or any(
            not isinstance(v, str) for v in dispatch["anti_hints"]):
        errors.append("dispatch.anti_hints: string list required")


def _validate_loop(obj: dict, errors: list[str]) -> None:
    loop = obj.get("loop")
    keys = {"monitor_focus", "ping_policy", "stall_rules"}
    if not isinstance(loop, dict):
        errors.append("loop: mapping required")
        return
    if set(loop) != keys:
        errors.append(f"loop: keys must be exactly {sorted(keys)}")
        return
    for field in ("monitor_focus", "stall_rules"):
        value = loop.get(field)
        if not isinstance(value, list) or any(
                not isinstance(v, str) for v in value):
            errors.append(f"loop.{field}: string list required")
    if not str(loop.get("ping_policy") or "").strip():
        errors.append("loop.ping_policy: non-empty string required")


def _validate_hooks(obj: dict, errors: list[str]) -> None:
    hooks = obj.get("hooks")
    if not isinstance(hooks, dict) or set(hooks) != {"cards"}:
        errors.append("hooks: mapping with exactly ['cards'] required")
        return
    cards = hooks.get("cards")
    if not isinstance(cards, list) \
            or any(not _CARD_ID_RE.match(str(c)) for c in cards):
        errors.append("hooks.cards: well-formed card ids required")


def _validate_amendments(obj: dict, errors: list[str]) -> None:
    amendments = obj.get("amendments")
    if not isinstance(amendments, list):
        errors.append("amendments: list required")
        return
    for i, amendment in enumerate(amendments):
        if not isinstance(amendment, dict) \
                or set(amendment) != {"param", "value", "evidence_refs"}:
            errors.append(
                f"amendments[{i}]: exactly "
                f"{sorted(('param', 'value', 'evidence_refs'))}")
            continue
        if not str(amendment.get("param") or "").strip():
            errors.append(f"amendments[{i}].param: empty")
        refs_list = amendment.get("evidence_refs")
        if not isinstance(refs_list, list) or not refs_list \
                or any(not str(r).strip() for r in refs_list):
            errors.append(
                f"amendments[{i}].evidence_refs: non-empty list required")


def validate_strategy(obj) -> list[str]:
    """Schema linter for round-strategy/1 ([] = clean). Enforces the
    exact section set — any constitution-side key fails here, which is
    the second half of the segment-discipline pin."""
    if not isinstance(obj, dict):
        return ["strategy: not a mapping"]
    errors: list[str] = []
    allowed_top = {"schema", "tick", "ts", "state_fingerprint",
                   "composed_from", "content_hash", "dispatch", "loop",
                   "hooks", "amendments"}
    unknown = sorted(set(obj) - allowed_top)
    if unknown:
        errors.append("unknown top-level keys: " + ",".join(unknown))
    _validate_identity(obj, errors)
    _validate_dispatch(obj, errors)
    _validate_loop(obj, errors)
    _validate_hooks(obj, errors)
    _validate_amendments(obj, errors)
    return errors


# ---------------------------------------------------------------- compose

def _budget_hint(snap: dict) -> str | None:
    """The mechanical budget face (state bucket, not learned content)."""
    budget = snap.get("budget") or {}
    if not budget.get("present"):
        return None
    return f"bucket:{budget.get('bucket')}"


def _silent_sections(snap: dict) -> dict:
    """Cold-start / below-threshold silence: no lead, no cards, no
    focus — the policy constants still render (they are loop plumbing,
    not learned claims). WS3 (#544) lifts exactly ONE field out of the
    silence via _cold_sections (the seeded intake lead); everything
    else in this dict is the unchanged silence contract."""
    return {
        "dispatch": {"method_lead": None, "anti_hints": [],
                     "budget_hint": _budget_hint(snap)},
        "loop": {"monitor_focus": [], "ping_policy": PING_POLICY,
                 "stall_rules": list(STALL_RULES)},
        "hooks": {"cards": []},
        "amendments": [],
    }


def _cold_sections(ws: Path, snap: dict) -> dict:
    """The below-n_min sections (WS3 #544): the silence plus — when a
    valid llm-prior/1 doc exists — its top family as method_lead. The
    seed REPLACES SILENCE, it does not claim signal: every other field
    stays byte-identical to _silent_sections, and a missing/corrupt
    prior degrades to exactly the old full silence (fail-open)."""
    sections = _silent_sections(snap)
    try:
        from rlvr import priors as _priors
        lead = _priors.intake_prior_lead(_priors.read_intake_prior(ws))
    except Exception as exc:  # noqa: BLE001 — never breaks compose, loud (#275)
        warn("compose.cold_seed_lead",
             f"{type(exc).__name__}: {exc} (fail-open: full silence)")
        lead = None
    if lead:
        sections = {
            **sections,
            "dispatch": {**sections["dispatch"], "method_lead": lead},
        }
    return sections


def compose(ws, tick: int, *, store: StrategyStore | None = None,
            n_min: int = DEFAULT_N_MIN,
            top_k: int = DEFAULT_TOP_K) -> dict:
    """THE single-point: one round-strategy object per decision event.

    Retrieval (read-only ledger fold + card library + store view) ->
    synthesis (deterministic templates) -> scheduling (threshold gate,
    staleness fade, decayed rank, top-k budget). Settlement accumulation
    runs first so the library is current (idempotent, content-addressed).
    Self-validates before returning (fail-closed compose)."""
    ws = Path(ws)
    tick = int(tick)
    if tick < 0:
        raise ValueError("tick: non-negative required")
    rows = rl.settled(ws)
    snap = state_signature.snapshot(ws)
    fp = state_signature.signature_hash(snap)
    store = store if store is not None else load_store(ws)

    refresh_cards(ws, tick=tick)
    cards = load_cards(ws)

    cell = store.cell_count(fp)
    evidence_count = len(rows) if cell is None else int(cell)
    if evidence_count < n_min:
        sections = _cold_sections(ws, snap)
    else:
        scheduled = schedule_cards(cards, store, settled_total=len(rows),
                                   top_k=top_k)
        anti = [render_card_block(c) for c in scheduled
                if c.get("kind") in ANTI_HINT_KINDS]
        sections = {
            "dispatch": {"method_lead": store.method_lead(fp),
                         "anti_hints": anti,
                         "budget_hint": _budget_hint(snap)},
            "loop": {"monitor_focus": sorted(
                         {str(c.get("scope_fingerprint"))
                          for c in scheduled}),
                     "ping_policy": PING_POLICY,
                     "stall_rules": list(STALL_RULES)},
            "hooks": {"cards": [str(c["id"]) for c in scheduled]},
            "amendments": [],
        }
    obj = {
        "schema": SCHEMA,
        "tick": tick,
        "ts": _utc_now_z(),
        "state_fingerprint": fp,
        "composed_from": sorted({str(r.get("rollout_id")) for r in rows}),
        **sections,
    }
    obj["content_hash"] = strategy_content_hash(
        {name: obj[name] for name in
         ("dispatch", "loop", "hooks", "amendments")})
    errors = validate_strategy(obj)
    if errors:
        raise ValueError("composed strategy invalid: " + "; ".join(errors))
    return obj


def _strategy_dir(ws: Path) -> Path:
    return ws / STRATEGY_DIR_REL


def _load_yaml(path: Path):
    doc, err = read_yaml(path)
    if doc is None and err is not None:
        warn("compose_io", f"{path.name}: {err}")
    return doc


def write_strategy(ws, obj: dict) -> dict:
    """Version one strategy object. Dedup: an object whose content_hash
    already exists on file (same tick or any earlier tick) is NOT written
    again — consumers skip on unchanged hash. A recomposition of an
    existing tick with new content overwrites that tick. Returns
    {"written", "changed", "path", "reason"}. Also re-emits the consumer
    seam projection (``write_seam``) so the strategy in force is always
    rendered where the loop prompt reads it (issue 462 W2)."""
    directory = _strategy_dir(Path(ws))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"tick-{int(obj['tick']):04d}.yaml"
    if path.exists():
        existing = _load_yaml(path)
        if isinstance(existing, dict) \
                and existing.get("content_hash") == obj["content_hash"]:
            write_seam(ws, obj)
            return {"written": False, "changed": False, "path": path,
                    "reason": "unchanged"}
    for other_path in sorted(directory.glob("tick-*.yaml")):
        other = _load_yaml(other_path)
        if isinstance(other, dict) \
                and other.get("content_hash") == obj["content_hash"]:
            write_seam(ws, obj)
            return {"written": False, "changed": False, "path": other_path,
                    "reason": "unchanged"}
    _atomic_write_text(path, yaml.safe_dump(obj, allow_unicode=True,
                                             sort_keys=True))
    write_seam(ws, obj)
    return {"written": True, "changed": True, "path": path, "reason": None}


# ------------------------------------------------------ consumer seam (W2)

def _predictions_section(ws: Path) -> dict | None:
    """The open-prediction backlog, dispatch-adjacent: when the ledger
    holds pending predictions, ONE line listing them so workers see
    observations their work could settle (count x age is the controller
    signal — the line cites both). Determinism note: the age term reads
    the clock, so an aging backlog legitimately re-renders (new content
    hash) — the state it describes genuinely changed. Fail-open: any
    ledger-face failure drops the section (loud), never the strategy."""
    try:
        from rlvr import prediction_ledger as pl  # noqa: PLC0415
        b = pl.backlog(ws)
        if not b.get("count"):
            return None
        items = "; ".join(
            f"{row.get('id')} — settle when: {row.get('discriminator')}"
            for row in pl.pending(ws))
        line = (f"open predictions: {b['count']} "
                f"(oldest {b['max_age_hours']:.0f}h): {items}")
        return {"title": "open-predictions", "body": line}
    except Exception as exc:  # noqa: BLE001 — fail-open, loud per the house rule
        warn("compose.predictions", f"{type(exc).__name__}: {exc}")
        return None


def _seam_sections(ws: Path, obj: dict) -> list[dict]:
    """The deterministic projection of one strategy object into the
    consumer seam's ``sections:[{title, body}]`` — every sentence
    attributable to the strategy's own fields (template faces only, no
    invention). The seam broadcasts what CHANGES: learned/attributable
    content only (lead + its budget context, anti-hints, monitor focus,
    cards). The loop policy constants (ping policy / stall rules) stay
    in the versioned tick objects — they are compose plumbing, identical
    in every strategy, and rendering them would break the cold-start
    silence the seam consumers contract for. The dispatch-lead section
    renders only when a LEAD exists: budget_hint is advisory context
    for the lead decision, and a lead-less strategy (below the evidence
    threshold) renders NOTHING whatever the workspace's budget
    telemetry says (the pre-existing consumer contract, now
    unconditional — 462 review MEDIUM-2). Empty-bodied sections are
    dropped."""
    cards = {str(c["id"]): c for c in load_cards(ws)}
    sections: list[dict] = []
    dispatch = obj.get("dispatch") or {}
    lead = str(dispatch.get("method_lead") or "").strip()
    if lead:
        lines = [f"method lead: prefer family {lead} for matching "
                 f"states at this decision point"]
        hint = str(dispatch.get("budget_hint") or "").strip()
        if hint:
            lines.append(f"budget: {hint}")
        sections.append({"title": "dispatch-lead", "body": "\n".join(lines)})
    pred = _predictions_section(ws)
    if pred:
        # dispatch-adjacent: immediately after the lead block when one
        # rendered, leading the section list when the strategy is silent
        sections.insert(
            1 if sections and sections[0]["title"] == "dispatch-lead"
            else 0,
            pred)
    anti = [str(a) for a in (dispatch.get("anti_hints") or [])
            if str(a).strip()]
    if anti:
        sections.append({"title": "anti-hints", "body": "\n".join(anti)})
    focus = [str(f) for f in ((obj.get("loop") or {}).get("monitor_focus")
                              or []) if str(f).strip()]
    if focus:
        sections.append({"title": "loop-watch",
                         "body": "monitor focus: " + ", ".join(focus)})
    card_blocks = [render_card_block(cards[str(cid)],
                                     segment=SEGMENT_STRATEGY)
                   for cid in (obj.get("hooks") or {}).get("cards") or []
                   if str(cid) in cards]
    if card_blocks:
        sections.append({"title": "cards", "body": "\n".join(card_blocks)})
    return sections


def write_seam(ws, obj: dict) -> dict:
    """Emit the consumer seam projection for one strategy object (issue
    462 W2): ``runs/round-strategy.json`` shaped ``{schema, round,
    sections}`` — ``round`` carries the strategy's tick (the round axis
    the object was composed at). Byte-idempotent and self-healing: the
    write face re-emits on every compose, so a deleted or corrupt seam
    is repaired by the next decision event. Fail-open with the module's
    own broad cage (the W2 review MEDIUM-1: a corrupt non-UTF-8 seam or
    a malformed on-disk card must WARN + skip, never raise out of the
    write face — the versioned tick write must always land)."""
    ws = Path(ws)
    path = ws / SEAM_REL
    try:
        doc = {"schema": SCHEMA, "round": int(obj["tick"]),
               "sections": _seam_sections(ws, obj)}
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                          indent=2) + "\n"
        if path.is_file() and path.read_text(encoding="utf-8",
                                             errors="replace") == text:
            return {"written": False, "path": path}
        _atomic_write_text(path, text)
        return {"written": True, "path": path}
    except Exception as exc:  # noqa: BLE001 — the seam never breaks the write
        warn("write_seam", f"{type(exc).__name__}: {exc}")
        return {"written": False, "path": path}


def read_strategy(ws, tick: int | None = None) -> dict | None:
    """The strategy in force: the given tick, else the latest (the
    resume-continuity read face — a resumed workspace continues the
    policy). None when nothing was ever composed."""
    directory = _strategy_dir(Path(ws))
    if not directory.is_dir():
        return None
    if tick is not None:
        return _load_yaml(directory / f"tick-{int(tick):04d}.yaml")
    ticks = sorted(directory.glob("tick-*.yaml"))
    for path in reversed(ticks):
        doc = _load_yaml(path)
        if doc is not None:
            return doc
    return None


from _common import utc_now_z as _utc_now_z  # the canonical leaf


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
