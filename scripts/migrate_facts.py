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

Facts NOT present in FACT_MIGRATION_MAP migrate via conservative defaults
(source=inference, slug from title, old promotion_gate kept) with loud warnings
— the curated semantic fixes (source enum, promotion condition) only exist for
the 865e8eb489b2935b745502026a81e1ef9a6ad6b9 workspace facts.

Usage:
    python scripts/migrate_facts.py <WORKSPACE> [--backup] [--dry-run] [--fact F001]
"""
from __future__ import annotations

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
    parse_frontmatter,
)

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

SAMPLE_HASH = "865e8eb489b2935b745502026a81e1ef9a6ad6b9"  # workspace sample filename

# #356 W3: skill root derived from this file — the pre-#356 F022 entry
# hardcoded the original author's absolute install path. Kept as a
# module-level derivation so every curated reference stays machine-agnostic.
SKILL_ROOT = Path(__file__).resolve().parent.parent
_CRYPTO_TOOL = (SKILL_ROOT / "tools" / "crypto" / "crypto-tool.py").as_posix()

# ---------- curated migration map (workspace facts) ----------
# extra_provenance: list of (role, path, credibility) — credibility None → default
# excerpt: appended as "## Code excerpt" (quoted from the committed recompute
#   script, which is already a provenance entry) — never invented.
FACT_MIGRATION_MAP = {
    "F001": dict(
        slug="sample-overview", title="Sample Overview — MSVC 19.43, no packer",
        source="static-decompile",
        promotion_gate=("Runtime execution capture showing the process runs without unpacking: "
                        "EP memory matches on-disk .text layout, no section allocation/decompression "
                        "(dynamic confirmation of DIE packer=null)"),
        extra_provenance=[
            ("other", "evidence/die.json", "B2"),
            ("other", "evidence/signature.json", "B3"),
            ("decompiled_c", "evidence/static-ghidra.json", "A2"),
        ],
    ),
    "F002": dict(
        slug="family-attribution", title="Family Attribution — Steam fake CDK scam, DLL hijack",
        source="vt-pivot",
        promotion_gate=("Dynamic capture linking the executed sample to the attributed infrastructure: "
                        "VT/sandbox execution_parents chain or VM traffic to *.steam.work domains "
                        "from this sample's process"),
        extra_provenance=[
            ("other", "evidence/cti-vt.json", "C5"),
            ("other", "evidence/cti-correlated.json", "C5"),
        ],
        alternatives=[
            {"hypothesis": "Attributed to a named threat actor (APT)",
             "rejected_because": ("H0_unattributed — commodity consumer-scam profile (9/12), "
                                  "community-grade CTI only, no APT TTP/infrastructure; "
                                  "body: 'Attribution: H0_unattributed — no named threat actor'")},
        ],
    ),
    "F003": dict(
        slug="obfuscation-xor-cfg", title="Obfuscation — XOR key=index+0x4d, CFG",
        source="static-decompile",
        promotion_gate=("Runtime capture of XOR decode executed at load — decoded cdk.steam.work "
                        "string recovered from process memory before C2 use"),
        extra_provenance=[
            ("other", "evidence/die.json", "B2"),
            ("decompiled_c", "evidence/static-ghidra.json", "A2"),
        ],
    ),
    "F004": dict(
        slug="import-table", title="Imports — 601 imports/16 DLLs, capability map",
        source="static-decompile",
        promotion_gate=("Runtime IAT walk confirming 601 imports/16 DLLs resolved at load — "
                        "matches static table byte-exact"),
        extra_provenance=[("other", "evidence/imports-categorized.json", "B3")],
        excerpt=(
            "```python\n"
            "pe = pefile.PE(SAMPLE)\n"
            "imps = [i.name for e in pe.DIRECTORY_ENTRY_IMPORT for i in e.imports if i.name]\n"
            "print(f'imports={len(imps)} dlls={len(pe.DIRECTORY_ENTRY_IMPORT)}')\n"
            "```\n"
            "Full script: runs/verify-f004.py"
        ),
    ),
    "F005": dict(
        slug="xor-string-decode", title="XOR Decode — cdk.steam.work@0x21A640",
        source="static-decompile",
        promotion_gate=("Runtime breakpoint at 0x21A640 after decode showing plaintext "
                        "cdk.steam.work in memory"),
        extra_provenance=[("recompute_script", "evidence/xor-decode.py", "A2")],
        excerpt=(
            "```python\n"
            "XOR_BASE = 0x4D\n"
            "def xor_decode(blob): return bytes([(b ^ ((i + XOR_BASE) & 0xFF)) for i, b in enumerate(blob)])\n"
            "# Test 1: known encoded form of \"cdk.steam.work\" at file offset 0x21A640\n"
            "encoded_cdk = binary[0x21A640:enc_end]\n"
            "decoded_cdk_text = xor_decode(encoded_cdk).split(b\"\\x00\")[0]\n"
            "```\n"
            "Full script: runs/verify-f005.py"
        ),
    ),
    "F006": dict(
        slug="entry-flow", title="Entry Flow — EP→FUN_140005040 dispatcher",
        source="static-decompile",
        promotion_gate="VM debugger trace of EP 0x18989c → CRT init → FUN_140005040 dispatch",
        extra_provenance=[("decompiled_c", "evidence/callgraph.txt", "A2")],
    ),
    "F007": dict(
        slug="c2-wininet", title="C2 Protocol — WININET HTTP full stack",
        source="static-decompile",
        promotion_gate=("Frida hook capture of WININET HttpOpenRequestW/HttpSendRequestW session "
                        "to cdk.steam.work from this process"),
        extra_provenance=[("decompiled_c", "evidence/callgraph.txt", "A2")],
        depends_on=["F005-xor-string-decode", "F006-entry-flow"],
    ),
    "F008": dict(
        slug="dll-hijack", title="DLL Hijack — dropper plants hid.dll",
        source="static-decompile",
        promotion_gate=("VM capture of pws.ps1.txt → hid.dll write → LoadLibrary(NewSteamValve.exe) "
                        "chain in one execution session"),
        extra_provenance=[
            ("decompiled_c", "evidence/callgraph.txt", "A2"),
            ("other", "evidence/cti-vt-related-11649357498f.json", "C5"),
            ("other", "evidence/strings-raw.json", "B3"),
        ],
    ),
    "F009": dict(
        slug="anti-analysis", title="Anti-Analysis — only IsDebuggerPresent",
        source="static-decompile",
        promotion_gate=("VM execution showing only the IsDebuggerPresent anti-analysis call and "
                        "no anti-VM/anti-sandbox behavior"),
        extra_provenance=[
            ("decompiled_c", "evidence/callgraph.txt", "A2"),
            ("decompiled_c", "evidence/static-ghidra.json", "A2"),
        ],
    ),
    "F010": dict(
        slug="file-proc-reg", title="File/Proc/Reg — file active, proc kill, reg absent",
        source="static-decompile",
        promotion_gate=("Runtime API monitor confirming file I/O (CreateFileW/WriteFile), process "
                        "enumeration + TerminateProcess, and no registry writes"),
        extra_provenance=[("decompiled_c", "evidence/callgraph.txt", "A2")],
        depends_on=["F004-import-table"],
    ),
    "F011": dict(
        slug="ioc-extraction", title="IOC Extraction — network/host/behavior indicators",
        source="inference",
        promotion_gate=("Live telemetry/DNS capture confirming extracted IOCs (cdk.steam.work "
                        "query, StoreCDK#1 mutex) from the sample's own execution"),
        depends_on=[
            "F001-sample-overview", "F002-family-attribution", "F003-obfuscation-xor-cfg",
            "F004-import-table", "F005-xor-string-decode", "F006-entry-flow",
            "F007-c2-wininet", "F008-dll-hijack", "F009-anti-analysis", "F010-file-proc-reg",
            "F013-mutex", "F014-resources", "F015-dropper-chain", "F016-sections",
            "F017-crypto-negative", "F018-code-structure",
        ],
    ),
    "F013": dict(
        slug="mutex", title="Mutex — StoreCDK#1 single-instance",
        source="static-decompile",
        promotion_gate="Frida hook capture of CreateMutexW(name=StoreCDK#1) returning a valid handle",
        extra_provenance=[
            ("decompiled_c", "evidence/callgraph.txt", "A2"),
            ("other", "mal-recon/865e8eb489b2935b745502026a81e1ef9a6ad6b9/report.json", "B3"),
        ],
    ),
    "F014": dict(
        slug="resources", title="Resources — icons+manifest, no version",
        source="static-decompile",
        promotion_gate=("Runtime capture of resource load — manifest parsed, icons rendered, "
                        "no RT_VERSION read"),
        extra_provenance=[
            ("other", "runs/worker-c014-resources.json", "B3"),
            ("recompute_script", "runs/worker-c014-extract.py", "A2"),
        ],
        excerpt=(
            "```python\n"
            "pe = pefile.PE(SAMPLE)\n"
            "rsrc = [s for s in pe.sections if s.Name.rstrip(b'\\x00') == b'.rsrc'][0]\n"
            "needle = 'VS_VERSION_INFO'.encode('utf-16-le')\n"
            "print('rsrc_va=%s rsrc_raw=%d vs_version=%d' % (hex(rsrc.VirtualAddress),\n"
            "      rsrc.SizeOfRawData, data.count(needle)))\n"
            "```\n"
            "Full script: runs/verify-f014.py"
        ),
    ),
    "F015": dict(
        slug="dropper-chain", title="Dropper Chain — pws.ps1.txt→hid.dll→NewSteamValve",
        source="vt-pivot", boundary_type="link_not_closed",
        promotion_gate=("Our-VM capture of the complete drop chain in one session (pws.ps1.txt "
                        "fetched → hid.dll written → NewSteamValve.exe loaded) with stage hashes "
                        "matching the VT-derived values"),
        extra_provenance=[
            ("other", "evidence/cti-vt.json", "C5"),
            ("other", "evidence/cti-vt-related-11649357498f.json", "C5"),
        ],
        depends_on=["F008-dll-hijack"],
    ),
    "F016": dict(
        slug="sections", title="Sections — 6 sections, no anomalies",
        source="static-decompile",
        promotion_gate=("Runtime VirtualQuery over section VA ranges matching the on-disk layout "
                        "with no RWX anomaly"),
        excerpt=(
            "```python\n"
            "for i, sec in enumerate(pe.sections):\n"
            "    name = sec.Name.rstrip(b\"\\x00\").decode(\"ascii\", errors=\"replace\")\n"
            "    entropy = shannon_entropy(raw_bytes)\n"
            "    # anomaly flags: RWX if (chars & 0xE0000000) == 0xE0000000,\n"
            "    # HIGH_ENTROPY if entropy > 7.0, VIRTUAL_SIZE > rsd*3\n"
            "```\n"
            "Full script: runs/verify-f016.py"
        ),
    ),
    "F017": dict(
        slug="crypto-negative", title="Crypto — no standard primitives",
        source="static-decompile",
        promotion_gate="",  # pure_negative: gate MUST stay empty
        excerpt=(
            "```python\n"
            "aes_sbox = bytes([0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, ...])  # first 32 bytes\n"
            "findings[\"AES\"][\"Sbox_first32\"] = {\"hits\": len(search_bytes(data, aes_sbox))}\n"
            "# plus: hash IV constants (0x67452301 MD5 H0, 0x428a2f98 SHA256 K[0], ...),\n"
            "# CRC32 poly 0xEDB88320, base64 alphabets, crypto keywords — hit counts only\n"
            "```\n"
            "Full script: runs/verify-f017.py"
        ),
    ),
    "F018": dict(
        slug="code-structure", title="Code Structure — 7198 funcs, MFC framework",
        source="static-decompile",
        promotion_gate=("Runtime trace of MFC framework init (AfxWinMain/CWinApp dispatch) "
                        "confirming the 7198-function structure"),
        extra_provenance=[("decompiled_c", "evidence/callgraph.txt", "A2")],
        depends_on=["F006-entry-flow"],
    ),
    "F020": dict(
        slug="killchain", title="Killchain — 7-stage static reconstruction",
        source="inference",
        promotion_gate="VM dynamic execution (C-012) confirming the 7 killchain stages in sequence",
        depends_on=[
            "F001-sample-overview", "F002-family-attribution", "F003-obfuscation-xor-cfg",
            "F004-import-table", "F005-xor-string-decode", "F006-entry-flow",
            "F007-c2-wininet", "F008-dll-hijack", "F009-anti-analysis", "F010-file-proc-reg",
            "F011-ioc-extraction", "F013-mutex", "F014-resources", "F015-dropper-chain",
            "F016-sections", "F017-crypto-negative", "F018-code-structure",
        ],
    ),
    "F021": dict(
        slug="verdict", title="Final Verdict — MALICIOUS commodity CDK-scam dropper",
        source="inference",
        promotion_gate=("C-012 dynamic confirmation of malicious behaviors + independent "
                        "redteam verdict CONFIRMED on all primary questions"),
        extra_provenance=[("other", "evidence/verdict.json", "B3")],
        depends_on=[
            "F001-sample-overview", "F002-family-attribution", "F003-obfuscation-xor-cfg",
            "F004-import-table", "F005-xor-string-decode", "F006-entry-flow",
            "F007-c2-wininet", "F008-dll-hijack", "F009-anti-analysis", "F010-file-proc-reg",
            "F011-ioc-extraction", "F013-mutex", "F014-resources", "F015-dropper-chain",
            "F016-sections", "F017-crypto-negative", "F018-code-structure", "F020-killchain",
        ],
        alternatives=[
            {"hypothesis": "APT or targeted attack tool",
             "rejected_because": ("body 'IS NOT: APT, ransomware, worm, packed, or the payload "
                                  "itself' — ordinary commodity level, no APT TTP")},
            {"hypothesis": "Benign or PUA software",
             "rejected_because": ("9/12 maliciousness score, VT 37/71, dropper chain + revoked-cert "
                                  "hid.dll payload — body verdict MALICIOUS")},
        ],
    ),
    "F022": dict(
        slug="xoradd-enc-layer",
        title="C-022 加密层识别与明文恢复 — XOR/ADD self-syncing stream key=0x01",
        source="inference", boundary_type="observation",
        promotion_gate=("独立 verifier 复现 xor-add --mode decrypt --key 1 → dec1 sha256 "
                        "fd92b2d9418444e7b3fa93fdff5cc0cd63442fd21ed9c3c916fe88c526edc190 "
                        "比对通过且结构自洽确认"),
        provenance_override=[
            ("sample_raw", "test-scope/sample_enc.bin", "A1"),
            ("recompute_script", _CRYPTO_TOOL, "A2"),
        ],
        extension_override={
            "claim": "C-022 加密层识别与明文恢复 (test-scope/sample_enc.bin)",
            "reproduce": (f"python {_CRYPTO_TOOL} "
                          "xor-add --mode decrypt --key 1 --in ../test-scope/sample_enc.bin --reproduce"),
            "expected": "output_sha256=fd92b2d9418444e7b3fa93fdff5cc0cd63442fd21ed9c3c916fe88c526edc190",
            "verified": "pending",
        },
    ),
}

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


def _migrate_frontmatter(fid: str, fm: dict, body: str, ws: Path,
                         claim_map: dict, errors: list, warnings: list) -> dict | None:
    entry = FACT_MIGRATION_MAP.get(fid)
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
                        "curate FACT_MIGRATION_MAP for semantic accuracy")
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
                        "semantic fix requires a FACT_MIGRATION_MAP entry")
    # provenance
    prov = []
    if entry and entry.get("provenance_override"):
        source_entries = entry["provenance_override"]
    else:
        source_entries = [(str(p.get("role")), str(p.get("path", "")), None)
                          for p in (fm.get("provenance") or [])
                          if isinstance(p, dict)]
        source_entries += [(r, p, c) for (r, p, c) in (entry.get("extra_provenance") or [])]
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


def migrate_fact(path: Path, ws: Path, claim_map: dict, errors: list, warnings: list) -> bool:
    """Migrate one fact file in place. Returns True when the file was rewritten."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body, perr = parse_frontmatter(text)
    fid = str(fm.get("id") or "")
    m = re.fullmatch(r"F(\d{3,})", fid or "") or re.fullmatch(r"F(\d{3,})", path.stem)
    if not m:
        warnings.append(f"{path.name}: not an F<NNN> fact file — skipped")
        return False
    key = f"F{int(m.group(1)):03d}"
    # idempotency: already slugged + reviewed → skip
    if fm.get("id") and ID_RE.fullmatch(str(fm["id"])) and fm.get("last_reviewed"):
        return False
    new_fm = _migrate_frontmatter(key, fm or {}, body, ws, claim_map, errors, warnings)
    if new_fm is None:
        return False
    rendered = render_frontmatter(new_fm)
    entry = FACT_MIGRATION_MAP.get(key)
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
        "# Facts Index — 865e8eb489b2935b745502026a81e1ef9a6ad6b9",
        "",
        f"## Status: {status_summary}  ({len(rows)} facts total)",
        "",
    ]
    lines += [f"{d['id']} | {d['workflow_status']} | {d['claim_id']} | {d['title']}" for d in rows]
    lines += [""]
    lines += [l for l in preserved if l.strip()]
    idx_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def migrate_workspace(ws: Path, *, backup: bool = False, dry_run: bool = False,
                      only: str | None = None) -> dict:
    """Migrate all facts in <ws>/facts/. Returns a report dict."""
    facts_dir = ws / "facts"
    report = {"migrated": [], "errors": [], "warnings": [], "backup": None}
    if not facts_dir.is_dir():
        report["errors"].append(f"{facts_dir} not a directory")
        return report
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
            fm, _body, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            report["migrated"].append({"file": p.name, "dry_run": True})
            continue
        changed = migrate_fact(p, ws, claim_map, report["errors"], report["warnings"])
        if changed:
            fm, _b, _e = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
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
    ap = argparse.ArgumentParser(description="migrate old-format facts to the aligned schema (#336)")
    ap.add_argument("ws", type=Path, help="workspace root (contains facts/)")
    ap.add_argument("--backup", action="store_true",
                    help="backup facts/ to facts.bak-pre336/ before migrating")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--fact", help="migrate only this fact (e.g. F001)")
    args = ap.parse_args(argv)
    report = migrate_workspace(args.ws, backup=args.backup, dry_run=args.dry_run, only=args.fact)
    for w in report["warnings"]:
        print(f"  warn  {w}")
    for e in report["errors"]:
        print(f"  ERR   {e}")
    print(f"migrated: {len([m for m in report['migrated'] if not m.get('dry_run')])} facts "
          f"(dry-run: {len([m for m in report['migrated'] if m.get('dry_run')])})")
    if report["backup"]:
        print(f"backup: {report['backup']}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
