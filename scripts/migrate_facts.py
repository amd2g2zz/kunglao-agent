#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_facts.py — migrate old-format kunglao facts to the aligned schema (#336).

Old kunglao fact frontmatter drifted from malware-veri-notes
references/frontmatter-schema.md: missing title/created/last_reviewed/confidence,
id without slug, free-text source, provenance without content_sha256, workflow
states (PARTIALLY-VERIFIED) sitting in the schema `status` slot, and
promotion_gate holding a verification command instead of a promotion condition.

This script applies a deterministic, idempotent migration:

  - id: F<NNN> → F<NNN>-<slug>  (slug curated per fact or derived from title)
  - adds title / created (file mtime date, never backdated) / last_reviewed
  - source: free text → 8-value enum (curated per fact)
  - status: workflow state → schema status + verify_status + confidence
      PARTIALLY-VERIFIED → status INFERRED, verify_status partial, confidence medium
      PROVEN            → status PROVEN,  verify_status passes,  confidence high
      pure_negative     → status NEGATIVE, verify_status partial, confidence high,
                          confidence_zh unsupported, promotion_gate emptied
  - promotion_gate: verification command → real promotion condition (curated)
  - provenance entries: adds content_sha256 (computed from the artifact) +
    credibility (Admiralty A1-F6, role/path defaults, curated overrides)
  - kunglao extension layer preserved byte-exact: claim/reproduce/expected/verified
  - claim_id: kept, or derived from facts/_INDEX.md → claim-register.yaml → body
  - facts/_INDEX.md regenerated (workflow-layer status column, slugged ids)
  - notes/*.md facts_used/depends_on + bold **F0NN** body refs re-pointed to new ids

Facts NOT covered by an opt-in --map migrate via conservative defaults
(source=inference, slug from title, old promotion_gate kept) with loud warnings.
#809: curated maps are no longer built in — a map must be loaded explicitly via
--map <path.json> ({"sample_sha256": ..., "facts": {...}}) AND the workspace
bins/ fingerprint must match the map's sample_sha256, otherwise the map goes
INERT (conservative defaults + loud warning + env_incident audit). The built-in
per-workspace table was the #809 cross-sample poisoning vector.

Usage:
    python scripts/migrate_facts.py <WORKSPACE> [--map MAP.json] [--backup] [--dry-run] [--fact F001]
"""
from __future__ import annotations

import kunglao_log  # noqa: E402
import argparse
import datetime
import hashlib
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lint_facts import (  # type: ignore
    ID_RE,
    VALID_CONFIDENCE_ZH,
    _parse_kv_block,
)


# #863 conflict ruling: migrate_facts carries its OWN frontmatter parser.
# This is a one-shot migration tool — it parses PRE-migration fact shapes,
# so it keeps the full tolerant semantics (yaml-first, kv fallback) inline
# instead of importing lint_facts.parse_frontmatter (whose lint-side
# contract hardens independently of this tool; the tool retires with its
# own luggage). The low-level kv block parser stays in lint_facts (#863
# ruling keeps it there) and is reused as-is.
def _coerce_yaml_scalars(obj):
    if isinstance(obj, datetime.datetime):
        return obj.date().isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _coerce_yaml_scalars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_yaml_scalars(v) for v in obj]
    return obj


def _parse_frontmatter(text: str):
    """Return (fm, body, error). fm={} when no fence; error set when
    unparseable. Tolerant semantics: yaml-first, kv fallback (the pre-
    migration shapes this tool exists to migrate are not strict YAML)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, "no-frontmatter"
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}, text, "no-closing-fence"
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])
    if yaml is not None:
        try:
            fm = yaml.safe_load(fm_text)
            if isinstance(fm, dict):
                return _coerce_yaml_scalars(fm), body, None
        except yaml.YAMLError:
            pass
    fm = _parse_kv_block(lines[1:end])
    return fm, body, "yaml-unparseable"

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


# #356 W3: skill root derived from this file — the pre-#356 F022 entry
# hardcoded the original author's absolute install path. Kept as a
# module-level derivation so every curated reference stays machine-agnostic.
SKILL_ROOT = Path(__file__).resolve().parent.parent
_CRYPTO_TOOL = (SKILL_ROOT / "tools" / "crypto" / "crypto-tool.py").as_posix()

# ---------- curated migration map (workspace facts) ----------
# extra_provenance: list of (role, path, credibility) — credibility None → default
# excerpt: appended as "## Code excerpt" (quoted from the committed recompute
#   script, which is already a provenance entry) — never invented.
FACT_MIGRATION_MAP: dict = {}  # #809: curated maps are opt-in only (--map <json>); the built-in table was the #809 poison vector

# ---------- generic defaults ----------

DEFAULT_CREDIBILITY = {
    "sample_raw": "A1", "decompiled_c": "A2", "disassembled_s": "A2",
    "recompute_script": "A2", "hex_bytes_inline": "A1", "capture_log": "A1",
    "screenshot": "A1", "public_doc": "A2", "other": "B3",
}

WORKFLOW_TO_SCHEMA = {
    "PROVEN": ("PROVEN", "passes", "high", "可确认"),
    "PARTIALLY-VERIFIED": ("INFERRED", "partial", "medium", "倾向于"),
}

SLUG_RE = re.compile(r"[^a-z0-9]+")
CLAIM_BODY_RE = re.compile(r"^claim:\s*(C-\d{3,})", re.M)


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _default_credibility(role: str, path: str) -> str:
    if "cti-" in path:
        return "C5"
    return DEFAULT_CREDIBILITY.get(role, "B3")


def _slugify(text: str) -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:48].rstrip("-")


def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if s == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./@:+=\-]*[A-Za-z0-9_./:@=]", s) or re.fullmatch(r"[A-Za-z0-9_\-]+", s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_prov_entry(p: dict) -> str:
    parts = [f"role: {_yaml_scalar(p.get('role'))}"]
    if p.get("path") is not None:
        parts.append(f"path: {_yaml_scalar(p['path'])}")
    if p.get("url") is not None:
        parts.append(f"url: {_yaml_scalar(p['url'])}")
    if p.get("bytes") is not None:
        parts.append(f"bytes: {_yaml_scalar(p['bytes'])}")
    parts.append(f"content_sha256: {_yaml_scalar(p.get('content_sha256'))}")
    parts.append(f"credibility: {_yaml_scalar(p.get('credibility'))}")
    return "{ " + ", ".join(parts) + " }"


def render_frontmatter(fm: dict) -> str:
    """Render frontmatter preserving the inline-provenance shape kunglao_verify
    (#332) parses with its _INLINE_PROV_ENTRY_RE regex — inline flow mappings."""
    lines = ["---"]
    order = ["id", "type", "title", "status", "verify_status", "created",
             "last_reviewed", "source", "confidence", "claim_id",
             "boundary_type", "promotion_gate", "confidence_zh",
             "provenance", "alternatives", "depends_on",
             "claim", "reproduce", "expected", "verified"]
    for key in order:
        if key not in fm:
            continue
        v = fm[key]
        if key == "provenance":
            lines.append("provenance:")
            for p in v:
                lines.append("  - " + _render_prov_entry(p))
        elif key in ("alternatives", "depends_on"):
            lines.append(f"{key}:")
            for item in v:
                if isinstance(item, dict):
                    lines.append("  - { " + ", ".join(
                        f"{k}: {_yaml_scalar(val)}" for k, val in item.items()) + " }")
                else:
                    lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------- migration ----------

def _read_index_claim_map(ws: Path) -> dict:
    """F<NNN> → claim_id from facts/_INDEX.md (F<id> | <status> | <claim> | <title>)."""
    out: dict = {}
    idx = ws / "facts" / "_INDEX.md"
    if not idx.exists():
        return out
    for line in idx.read_text(encoding="utf-8", errors="replace").splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        m = re.fullmatch(r"F(\d{3,})", parts[0])
        if m and re.fullmatch(r"C-\d{3,}", parts[2]):
            out[f"F{int(m.group(1)):03d}"] = parts[2]
    return out


def _read_register_claim_map(ws: Path) -> dict:
    """F<NNN> → claim_id from claim-register.yaml (claims[].fact → claims[].id)."""
    out: dict = {}
    reg = ws / "claim-register.yaml"
    if not reg.exists() or yaml is None:
        return out
    try:
        data = yaml.safe_load(reg.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return out
    for c in (data or {}).get("claims") or []:
        fact = str(c.get("fact") or "")
        m = re.fullmatch(r"F(\d{3,})", fact)
        if m and c.get("id"):
            out[f"F{int(m.group(1)):03d}"] = str(c["id"])
    return out


def _workflow_status(fm: dict) -> str:
    st, vs = fm.get("status"), fm.get("verify_status")
    if st == "PROVEN" and vs == "passes":
        return "PROVEN"
    if st in ("INFERRED", "NEGATIVE") and vs == "partial":
        return "PARTIALLY-VERIFIED"
    if st == "NEGATIVE":
        return "NEGATIVE"
    if st == "DEFERRED":
        return "DEFERRED"
    return str(st or "OPEN")


def _load_map(path) -> dict:
    """Load an explicit --map JSON: {"sample_sha256": str, "facts": {F-id: entry}}."""
    import json
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("facts"), dict):
        raise ValueError('map JSON must be {"sample_sha256": str, "facts": {...}}')
    return data


def _workspace_sample_sha256(ws: Path) -> str | None:
    """Content fingerprint of the workspace sample (bins/ files, order-stable)."""
    bins = ws / "bins"
    if not bins.is_dir():
        return None
    files = sorted(p for p in bins.rglob("*") if p.is_file())
    if not files:
        return None
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode("utf-8", "replace"))
        h.update(p.read_bytes())
    return h.hexdigest()


def _migrate_frontmatter(fid: str, fm: dict, body: str, ws: Path,
                         claim_map: dict, errors: list, warnings: list,
                         map_facts: dict | None = None) -> dict | None:
    entry = (map_facts or {}).get(fid)
    old_status = str(fm.get("status", "")).upper()
    if not old_status and body:
        # body-only facts (F022 pre-migration shape) declare workflow status in
        # the body header: "status: PARTIALLY-VERIFIED (awaiting independent verifier)"
        m = re.search(r"^status:\s*([A-Z-]+)", body, re.M)
        if m:
            old_status = m.group(1).upper().strip(" -")
    old_bt = fm.get("boundary_type")
    if old_bt is None and body:
        m = re.search(r"^boundary_type:\s*([a-z_]+)", body, re.M)
        if m:
            old_bt = m.group(1)
    new: dict = dict(fm)  # never mutate input
    new["type"] = "fact"
    # legacy boundary vocabulary → schema enum
    LEGACY_BOUNDARY = {"positive_observation": "observation"}
    if old_bt in LEGACY_BOUNDARY:
        old_bt = LEGACY_BOUNDARY[old_bt]
    if old_bt:
        new["boundary_type"] = old_bt
    # id slug
    slug = entry["slug"] if entry else _slugify(str(fm.get("claim", ""))[:48])
    new["id"] = f"{fid}-{slug}"
    # title
    new["title"] = entry["title"] if entry else str(fm.get("claim", "")).strip()
    # status × verify_status × confidence × confidence_zh
    if old_status == "PROVEN":
        st, vs, conf, czh = WORKFLOW_TO_SCHEMA["PROVEN"]
    elif old_status == "PARTIALLY-VERIFIED" and old_bt == "pure_negative":
        st, vs, conf, czh = "NEGATIVE", "partial", "high", "不支持"
    elif old_status == "PARTIALLY-VERIFIED":
        st, vs, conf, czh = WORKFLOW_TO_SCHEMA["PARTIALLY-VERIFIED"]
    else:
        st, vs, conf, czh = old_status or "OPEN", "pending", fm.get("confidence"), fm.get("confidence_zh")
        warnings.append(f"fact {fid}: status {old_status!r} has no mapping rule — kept as-is")
    new["status"] = st
    new["verify_status"] = vs
    new["confidence"] = conf
    if czh:
        new["confidence_zh"] = czh
    # source enum
    if entry:
        new["source"] = entry["source"]
    else:
        new["source"] = "inference"
        warnings.append(f"fact {fid}: source mapped to 'inference' by conservative default — "
                        "provide a --map entry for semantic accuracy")
    # dates
    if "created" not in fm:
        p = ws / "facts" / f"{fid}.md"
        new["created"] = datetime.date.fromtimestamp(p.stat().st_mtime).isoformat()
    new["last_reviewed"] = datetime.date.today().isoformat()
    # claim_id: kept, then index, then register, then body
    if not fm.get("claim_id"):
        cid = claim_map.get(fid) or ""
        if not cid:
            m = CLAIM_BODY_RE.search(body or "")
            cid = m.group(1) if m else ""
        if cid:
            new["claim_id"] = cid
        else:
            errors.append(f"fact {fid}: cannot derive claim_id (no index/register/body match)")
    # boundary_type + promotion_gate semantics
    if entry and entry.get("boundary_type"):
        new["boundary_type"] = entry["boundary_type"]
    if old_bt == "pure_negative":
        new["promotion_gate"] = ""
    elif entry and entry.get("promotion_gate") is not None:
        new["promotion_gate"] = entry["promotion_gate"]
    elif entry is None:
        warnings.append(f"fact {fid}: promotion_gate left as old verification command — "
                        "semantic fix requires a --map entry")
    # provenance
    prov = []
    if entry and entry.get("provenance_override"):
        source_entries = entry["provenance_override"]
    else:
        source_entries = [(str(p.get("role")), str(p.get("path", "")), None)
                          for p in (fm.get("provenance") or [])
                          if isinstance(p, dict)]
        source_entries += [(r, p, c) for (r, p, c)
                           in ((entry or {}).get("extra_provenance") or [])]
    for role, path, cred in source_entries:
        item = {"role": role, "path": path}
        cred = cred or _default_credibility(role, path)
        item["credibility"] = cred
        resolved = Path(path) if Path(path).is_absolute() else ws / path
        sha = _sha256_file(resolved)
        if sha is None:
            errors.append(f"fact {fid}: provenance {path!r} not found — content_sha256 cannot be computed")
            sha = ""
        item["content_sha256"] = sha
        prov.append(item)
    if not prov:
        errors.append(f"fact {fid}: no provenance entries after migration")
    new["provenance"] = prov
    # alternatives / depends_on (curated only — never invented)
    if entry:
        if entry.get("alternatives"):
            new["alternatives"] = entry["alternatives"]
        if entry.get("depends_on"):
            new["depends_on"] = entry["depends_on"]
        if entry.get("extension_override"):
            new.update(entry["extension_override"])
    return new


def migrate_fact(path: Path, ws: Path, claim_map: dict, errors: list, warnings: list,
                 map_facts: dict | None = None) -> bool:
    """Migrate one fact file in place. Returns True when the file was rewritten."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body, perr = _parse_frontmatter(text)
    fid = str(fm.get("id") or "")
    m = re.fullmatch(r"F(\d{3,})", fid or "") or re.fullmatch(r"F(\d{3,})", path.stem)
    if not m:
        warnings.append(f"{path.name}: not an F<NNN> fact file — skipped")
        return False
    key = f"F{int(m.group(1)):03d}"
    # idempotency: already slugged + reviewed → skip
    if fm.get("id") and ID_RE.fullmatch(str(fm["id"])) and fm.get("last_reviewed"):
        return False
    new_fm = _migrate_frontmatter(key, fm or {}, body, ws, claim_map, errors, warnings,
                                  map_facts=map_facts)
    if new_fm is None:
        return False
    rendered = render_frontmatter(new_fm)
    entry = (map_facts or {}).get(key)
    out_body = body
    if entry and entry.get("excerpt"):
        out_body = body.rstrip("\n") + "\n\n## Code excerpt\n\n" + entry["excerpt"] + "\n"
    path.write_text(rendered + "\n" + out_body, encoding="utf-8")
    return True


def rewrite_notes(ws: Path, id_map: dict, warnings: list):
    notes_dir = ws / "notes"
    if not notes_dir.is_dir():
        return
    for p in sorted(notes_dir.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        new_text = text
        for old, new in id_map.items():
            new_text = re.sub(rf"^(\s*-\s*){re.escape(old)}$", rf"\g<1>{new}", new_text, flags=re.M)
            new_text = new_text.replace(f"**{old}**", f"**{new}**")
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            warnings.append(f"notes/{p.name}: fact references re-pointed to slugged ids")


def regenerate_index(ws: Path, migrated_facts: list[dict]):
    idx_path = ws / "facts" / "_INDEX.md"
    old_lines = idx_path.read_text(encoding="utf-8", errors="replace").splitlines() \
        if idx_path.exists() else []
    preserved = [l for l in old_lines
                 if not (l.startswith("F") and "|" in l)
                 and not l.startswith("## Status:")
                 and not l.startswith("# Facts Index")
                 and l.strip()]
    rows = sorted(migrated_facts, key=lambda d: d["id"])
    status_counts: dict = {}
    for d in rows:
        wf = d["workflow_status"]
        status_counts[wf] = status_counts.get(wf, 0) + 1
    status_summary = " / ".join(f"{n} {s}" for s, n in sorted(status_counts.items(), reverse=True))
    lines = [
        "# Facts Index",
        "",
        f"## Status: {status_summary}  ({len(rows)} facts total)",
        "",
    ]
    lines += [f"{d['id']} | {d['workflow_status']} | {d['claim_id']} | {d['title']}" for d in rows]
    lines += [""]
    lines += [l for l in preserved if l.strip()]
    idx_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def migrate_workspace(ws: Path, *, backup: bool = False, dry_run: bool = False,
                      only: str | None = None,
                      map_path: str | None = None) -> dict:
    """Migrate all facts in <ws>/facts/. Returns a report dict.

    #809: --map 显式加载 curated map；样本指纹不匹配 → map 整体 inert
    （conservative defaults + 响亮 warning + env_incident 落账）。
    malformed map → 预检 fail-closed（零写入即返回）。
    """
    facts_dir = ws / "facts"
    report = {"migrated": [], "errors": [], "warnings": [], "backup": None}
    if not facts_dir.is_dir():
        report["errors"].append(f"{facts_dir} not a directory")
        return report
    migration_map: dict = {}
    if map_path:
        try:
            map_meta = _load_map(map_path)
        except Exception as exc:  # noqa: BLE001 — fail-closed pre-flight
            msg = f"migration map unreadable/malformed: {exc}"
            report["errors"].append(msg)
            kunglao_log.emit(ws, actor="migrate_facts", action="env_incident",
                             detail=msg)
            return report
        ws_sha = _workspace_sample_sha256(ws)
        if ws_sha != str(map_meta.get("sample_sha256") or ""):
            msg = ("migration map INERT: workspace sample fingerprint "
                   f"{ws_sha or '<no bins/>!'} != map sample_sha256 — "
                   "conservative defaults only (#809)")
            report["warnings"].append(msg)
            print(f"  WARN  {msg}", file=sys.stderr)
            kunglao_log.emit(ws, actor="migrate_facts", action="env_incident",
                             detail=msg)
        else:
            migration_map = dict(map_meta.get("facts") or {})
    if backup and not dry_run:
        dest = ws / "facts.bak-pre336"
        if dest.exists():
            dest = ws / f"facts.bak-pre336-{datetime.datetime.now():%Y%m%dT%H%M%S}"
        shutil.copytree(facts_dir, dest)
        report["backup"] = str(dest)
    claim_map = {**_read_register_claim_map(ws), **_read_index_claim_map(ws)}
    id_map: dict = {}
    migrated_facts: list[dict] = []
    for p in sorted(facts_dir.glob("F*.md")):
        if p.name == "_INDEX.md" or not p.name.upper().startswith("F"):
            continue
        m = re.fullmatch(r"F(\d{3,})", p.stem)
        if not m:
            continue
        key = f"F{int(m.group(1)):03d}"
        if only and key != only:
            continue
        if dry_run:
            fm, _body, _ = _parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            report["migrated"].append({"file": p.name, "dry_run": True})
            continue
        changed = migrate_fact(p, ws, claim_map, report["errors"], report["warnings"],
                               map_facts=migration_map)
        if changed:
            fm, _b, _e = _parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            new_id = str(fm.get("id") or "")
            old_id = f"F{int(m.group(1)):03d}"
            if new_id and new_id != old_id:
                id_map[old_id] = new_id
            migrated_facts.append({
                "id": new_id,
                "claim_id": str(fm.get("claim_id") or ""),
                "title": str(fm.get("title") or ""),
                "workflow_status": _workflow_status(fm),
            })
            report["migrated"].append({"file": p.name, "old_id": old_id, "new_id": new_id})
    if not dry_run and migrated_facts:
        rewrite_notes(ws, id_map, report["warnings"])
        regenerate_index(ws, migrated_facts)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="migrate old-format facts to the aligned schema")
    ap.add_argument("ws", type=Path, help="workspace root (contains facts/)")
    ap.add_argument("--map", help="explicit curated map JSON: "
                    '{"sample_sha256": ..., "facts": {...}} (#809: opt-in + fingerprint-gated)')
    ap.add_argument("--backup", action="store_true",
                    help="backup facts/ to facts.bak-pre336/ before migrating")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--fact", help="migrate only this fact (e.g. F001)")
    args = ap.parse_args(argv)
    kunglao_log.emit(args.ws, actor="migrate_facts", action="claim_migrate",
                     detail=f"migration start map={args.map or '<none>'} "
                            f"backup={args.backup} dry_run={args.dry_run}")
    report = migrate_workspace(args.ws, backup=args.backup, dry_run=args.dry_run,
                               only=args.fact, map_path=args.map)
    for w in report["warnings"]:
        print(f"  warn  {w}")
    for e in report["errors"]:
        print(f"  ERR   {e}")
    n = len([m for m in report["migrated"] if not m.get("dry_run")])
    print(f"migrated: {n} facts "
          f"(dry-run: {len([m for m in report['migrated'] if m.get('dry_run')])})")
    if report["backup"]:
        print(f"backup: {report['backup']}")
    kunglao_log.emit(args.ws, actor="migrate_facts", action="claim_migrate",
                     detail=f"migration done migrated={n} "
                            f"errors={len(report['errors'])} "
                            f"warnings={len(report['warnings'])}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
