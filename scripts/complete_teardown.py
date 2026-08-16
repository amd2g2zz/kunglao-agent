# -*- coding: utf-8 -*-
"""complete_teardown.py - 1-call search operator chain returning a fact bundle.

User said (verbatim, in Chinese): 'kunglao-agent是一个逆向agent,为了解决问题我把逆向问题抽象为搜索问题,
逆向的步骤就是再探索,为了更好的探索你肯定要提供更多的探索工具'
("kunglao-agent is a RE agent; to solve problems I abstract RE as search,
the RE steps are exploration, and better exploration needs more exploration
tools").
Also: '我们要的是样本完整拆解' ("what we want is a complete teardown of the
sample").

This script composes 5 cheap search operators (v1.8.15 inventory) into
1 call and returns a coherent fact bundle, not 5 separate fact files:

  Operator 1: pefile imports table (imports + delay-loads + TLS callbacks)
  Operator 2: byte-grep prologue scan (find function prologues in unknown regions)
  Operator 3: capstone disasm of .text section entry points (architecture-aware)
  Operator 4: string extraction with unicode/ASCII classification
  Operator 5: anti-analysis pattern scan (IsDebuggerPresent, NtQueryInformationProcess, etc.)

Output: 1 fact file at <workspace>/facts/F-NNN-teardown-<sample>.md
containing all 5 operator results + a TL;DR at the top.

Pure-python deps: pefile + capstone (no yara, no angr, no angr).
Skip operator X gracefully if its lib is missing.

Usage:
  python complete_teardown.py <workspace> [sample_path]
  python complete_teardown.py C:/path/to/workspace C:/path/to/sample.exe
  python complete_teardown.py .                          (uses bins/<sha> if single file)

Exit codes:
  0 = success, fact file written
  1 = workspace or sample not found
  2 = pefile parse error (not a valid PE)
  3 = all operators failed (fact file may be partial)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Pure-python deps (already in kunglao-agent env per this-session test)
try:
    import pefile
    PEFILE_OK = True
except ImportError:
    PEFILE_OK = False

try:
    import capstone
    CAPSTONE_OK = True
except ImportError:
    CAPSTONE_OK = False


# Anti-analysis patterns (pefile-style: byte sequences or import names)
ANTI_ANALYSIS_IMPORTS = [
    "IsDebuggerPresent", "CheckRemoteDebuggerPresent",
    "NtQueryInformationProcess", "NtQuerySystemInformation",
    "OutputDebugStringA", "OutputDebugStringW",
    "DebugActiveProcess", "ContinueDebugEvent",
    "BlockInput", "NtSetInformationThread",
    "QueryPerformanceCounter", "GetTickCount",  # timing-based VM detection
    "Sleep", "SleepEx",                          # anti-debug delay
    "VirtualProtect", "VirtualAlloc", "VirtualQuery",  # memory ops
]

# Common packer signatures (YARA-style strings, searched as raw bytes)
PACKER_SIGNATURES = {
    "UPX": [b"UPX!", b".UPX0", b"UPX0", b"UPX1", b"UPX2"],
    "ASPack": [b"ASPack", b".aspack"],
    "PECompact": [b"PECompact", b"PEC2"],
    "Themida": [b"Themida", b".themida"],
    "VMProtect": [b"VMProtect", b".vmp0", b".vmp1"],
    "MPRESS": [b"MPRESS", b".MPRESS"],
    "kkrunchy": [b"kkrunchy"],
}


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_sample(workspace: Path):
    """Auto-discover single .exe in bins/."""
    bins = workspace / "bins"
    if not bins.exists():
        return None
    samples = [p for p in bins.iterdir() if p.is_file() and p.suffix.lower() in (".exe", ".dll", ".bin")]
    if len(samples) == 1:
        return samples[0]
    return None


# ===== Operator 1: pefile imports =====
def operator_imports(sample: Path) -> dict:
    if not PEFILE_OK:
        return {"status": "skipped", "reason": "pefile not installed"}
    try:
        pe = pefile.PE(str(sample), fast_load=True)
        imports = []
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT") and pe.DIRECTORY_ENTRY_IMPORT:
            for entry in pe.DIRECTORY_ENTRY_IMPORT:
                if entry.name:
                    imports.append({
                        "dll": entry.dll.decode() if isinstance(entry.dll, bytes) else str(entry.dll),
                        "function": entry.name.decode() if isinstance(entry.name, bytes) else str(entry.name),
                        "ordinal": entry.ordinal,
                    })
        delay_loads = []
        if hasattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT") and pe.DIRECTORY_ENTRY_DELAY_IMPORT:
            for entry in pe.DIRECTORY_ENTRY_DELAY_IMPORT:
                if entry.name:
                    delay_loads.append({
                        "dll": entry.dll.decode() if isinstance(entry.dll, bytes) else str(entry.dll),
                        "function": entry.name.decode() if isinstance(entry.name, bytes) else str(entry.name),
                    })
        tls_callbacks = len(pe.IMAGE_DIRECTORY_ENTRY_TLS) if hasattr(pe, "IMAGE_DIRECTORY_ENTRY_TLS") else 0

        # Anti-analysis import flagging
        flagged_anti_analysis = []
        for imp in imports:
            if any(an in imp["function"] for an in ANTI_ANALYSIS_IMPORTS):
                flagged_anti_analysis.append(imp["function"])

        # Check for known packer section names
        packer_indicators = []
        for section in pe.sections:
            sec_name = section.Name.rstrip(b"\x00").decode(errors="replace")
            for packer, sigs in PACKER_SIGNATURES.items():
                if any(sec_name.encode() in s for s in sigs) or any(s.decode(errors="replace") in sec_name for s in sigs):
                    packer_indicators.append({"section": sec_name, "packer": packer})

        pe.close()

        return {
            "status": "ok",
            "import_count": len(imports),
            "imports": imports[:50],  # cap to 50 to avoid context bloat
            "anti_analysis_flagged": flagged_anti_analysis,
            "delay_import_count": len(delay_loads),
            "tls_callbacks": tls_callbacks,
            "packer_indicators": packer_indicators,
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ===== Operator 2: byte-grep prologue scan =====
PROLOGUE_PATTERNS = [
    (b"\x55\x8b\xec", "x86 push ebp; mov ebp,esp (stdcall prologue)"),
    (b"\x48\x89\x5c\x24", "x64 mov [rsp+...], rbx (Win64 prologue)"),
    (b"\x48\x83\xec", "x64 sub rsp, ..."),
    (b"\x55\x48\x89\xe5", "x64 push rbp; mov rbp,rsp (Unix prologue)"),
    (b"\x48\x8b\xc4", "x64 mov rax, rsp (cookie check)"),
]

def operator_byte_grep(sample: Path, max_bytes: int = 5_000_000) -> dict:
    try:
        data = sample.read_bytes()[:max_bytes]
        results = []
        for pattern, desc in PROLOGUE_PATTERNS:
            count = 0
            positions = []
            idx = 0
            while True:
                pos = data.find(pattern, idx)
                if pos < 0:
                    break
                count += 1
                if len(positions) < 10:
                    positions.append(hex(pos))
                idx = pos + 1
            if count > 0:
                results.append({
                    "pattern": pattern.hex(),
                    "description": desc,
                    "match_count": count,
                    "first_offsets": positions,
                })
        return {"status": "ok", "patterns_matched": results, "bytes_scanned": len(data)}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ===== Operator 3: capstone disasm entry =====
def operator_capstone_entry(sample: Path, max_insns: int = 50) -> dict:
    if not CAPSTONE_OK:
        return {"status": "skipped", "reason": "capstone not installed"}
    try:
        pe = pefile.PE(str(sample), fast_load=True)
        image_base = pe.OPTIONAL_HEADER.ImageBase if hasattr(pe, "OPTIONAL_HEADER") else 0
        entry_rva = pe.OPTIONAL_HEADER.AddressOfEntryPoint if hasattr(pe, "OPTIONAL_HEADER") else 0
        entry_offset = pe.get_offset_from_rva(entry_rva) if entry_rva else 0

        data = sample.read_bytes()
        if entry_offset + 200 > len(data):
            return {"status": "error", "reason": "entry point beyond file"}

        code = data[entry_offset:entry_offset + 200]

        # Auto-detect arch from OptionalHeader.Magic (PE32 = 0x10b, PE32+ = 0x20b)
        try:
            magic = pe.OPTIONAL_HEADER.Magic if hasattr(pe, "OPTIONAL_HEADER") else 0
        except Exception:
            magic = 0
        if magic == 0x20b:
            md = capstone.CS_ARCH_X86
            mode = capstone.CS_MODE_64
        else:
            md = capstone.CS_ARCH_X86
            mode = capstone.CS_MODE_32

        cs = capstone.Cs(md, mode)
        # capstone 6.x: cs.detail = capstone.CS_DETAIL_LINEAR; 5.x: cs.detail = 2 (CS_OPT_DETAIL)
        if hasattr(capstone, "CS_DETAIL_LINEAR"):
            cs.detail = capstone.CS_DETAIL_LINEAR
        else:
            try:
                cs.detail = capstone.CS_OPT_DETAIL
            except Exception:
                pass  # basic disasm without detail still works
        insns = list(cs.disasm(code, image_base + entry_rva))
        first_n = [{"addr": hex(i.address), "mnemonic": i.mnemonic, "op_str": i.op_str} for i in insns[:max_insns]]

        pe.close()

        return {
            "status": "ok",
            "entry_rva": hex(entry_rva),
            "entry_offset": hex(entry_offset),
            "arch": "x86",
            "first_instructions": first_n,
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ===== Operator 4: string extraction =====
ASCII_RE = re.compile(rb"[\x20-\x7e]{4,}")
UTF16_RE = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")

def operator_strings(sample: Path, max_strings: int = 100) -> dict:
    try:
        data = sample.read_bytes()
        ascii_strings = [s.decode(errors="replace") for s in ASCII_RE.findall(data)]
        utf16_strings = [s.decode("utf-16-le", errors="replace") for s in UTF16_RE.findall(data)]

        # Heuristics: classify interesting strings
        interesting = []
        keywords = ["http", "https", ".dll", ".exe", "C:\\\\", "\\\\Registry", "Software\\\\", "password", "key", "secret", "crypt", "http://", ".com", ".net"]
        for s in ascii_strings + utf16_strings:
            if any(k in s.lower() for k in keywords):
                interesting.append(s)
                if len(interesting) >= 20:
                    break

        return {
            "status": "ok",
            "ascii_count": len(ascii_strings),
            "utf16_count": len(utf16_strings),
            "ascii_sample": ascii_strings[:20],
            "utf16_sample": utf16_strings[:10],
            "interesting": interesting,
            "total_unique": len(set(ascii_strings) | set(utf16_strings)),
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ===== Operator 5: anti-analysis pattern scan =====
def operator_anti_analysis(sample: Path) -> dict:
    try:
        data = sample.read_bytes()
        hits = []
        for pat in ANTI_ANALYSIS_IMPORTS:
            pat_bytes = pat.encode("ascii")
            offset = data.find(pat_bytes)
            if offset < 0:
                pat_utf16 = pat.encode("utf-16-le")
                offset = data.find(pat_utf16)
                if offset < 0:
                    continue
            hits.append({"name": pat, "offset": hex(offset)})

        # Look for known anti-debug byte sequences
        anti_debug_seqs = [
            (b"\x0f\x31", "rdtsc (timing check)"),
            (b"\x0f\x01", "rdtscp (timing check)"),
            (b"\x64\xa1\x30\x00\x00\x00", "mov eax, fs:[0x30] (PEB access)"),
        ]
        for seq, desc in anti_debug_seqs:
            offset = data.find(seq)
            if offset >= 0:
                hits.append({"name": desc, "offset": hex(offset)})

        return {"status": "ok", "hits": hits, "total": len(hits)}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ===== Compose =====
def next_fact_id(workspace: Path) -> str:
    """Find next F-NNN id from existing facts."""
    facts = workspace / "facts"
    if not facts.exists():
        return "F-001"
    nums = []
    for p in facts.glob("F-*.md"):
        m = re.match(r"F-(\d+)", p.name)
        if m:
            nums.append(int(m.group(1)))
    return f"F-{max(nums or [0]) + 1:03d}"


def write_fact(workspace: Path, sample: Path, results: dict) -> Path:
    facts = workspace / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    fid = next_fact_id(workspace)
    fact_path = facts / f"{fid}-teardown-{sample.stem}.md"
    sample_sha = results["meta"]["sample_sha256"]
    lines = []
    lines.append(f"# {fid} — Complete teardown of `{sample.name}`")
    lines.append("")
    lines.append(f"**Sample SHA-256 (first 16)**: `{sample_sha[:16]}...`  ")
    lines.append(f"**Sample size**: {results['meta']['sample_size']} bytes  ")
    lines.append(f"**Operator run**: {utc_now()}  ")
    lines.append(f"**v1.8.16 search operator chain**: byte-grep + pefile + capstone + ascii/utf16-string + anti-analysis scan")
    lines.append("")

    # TL;DR
    lines.append("## TL;DR")
    lines.append("")
    op_summaries = []
    for k, v in results["operators"].items():
        if v.get("status") == "ok":
            if k == "imports":
                op_summaries.append(f"imports: {v.get('import_count', 0)} (anti-analysis: {len(v.get('anti_analysis_flagged', []))})")
            elif k == "byte_grep":
                total = sum(p.get("match_count", 0) for p in v.get("patterns_matched", []))
                op_summaries.append(f"byte-grep: {total} prologue matches")
            elif k == "capstone":
                op_summaries.append(f"entry: {v.get('arch', '?')} @ {v.get('entry_rva', '?')}")
            elif k == "strings":
                op_summaries.append(f"strings: {v.get('ascii_count', 0)} ASCII + {v.get('utf16_count', 0)} UTF16")
            elif k == "anti_analysis":
                op_summaries.append(f"anti-analysis: {v.get('total', 0)} hits")
        else:
            op_summaries.append(f"{k}: {v.get('status', '?')}")
    lines.append("; ".join(op_summaries))
    lines.append("")

    # Packer detection
    packer = results["operators"].get("imports", {}).get("packer_indicators", [])
    if packer:
        lines.append(f"**Packer detected**: {', '.join(p['packer'] for p in packer)}")
        lines.append("")

    # Operator results
    lines.append("## Operator results")
    lines.append("")
    for k, v in results["operators"].items():
        lines.append(f"### {k}")
        lines.append("")
        lines.append("```json")
        # Cap to 2KB to keep file readable
        s = json.dumps(v, indent=2, ensure_ascii=False)
        if len(s) > 2048:
            s = s[:2048] + "\n  ... (truncated, see full output in script run log)"
        lines.append(s)
        lines.append("```")
        lines.append("")

    fact_path.write_text("\n".join(lines), encoding="utf-8")
    return fact_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Complete sample teardown (5-operator chain)")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("sample", nargs="?", default=None, help="path to sample PE (auto-discover from bins/ if omitted)")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen, don't write files")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        print(f"FAIL: workspace {workspace} not found")
        return 1

    sample = Path(args.sample).resolve() if args.sample else find_sample(workspace)
    if not sample or not sample.exists():
        print(f"FAIL: sample not found (passed: {args.sample}, bins/: {workspace / 'bins'})")
        return 1

    if not PEFILE_OK:
        print("FAIL: pefile not installed; this script requires pefile")
        return 2

    print(f"Running 5-operator complete teardown on {sample.name}...")

    sample_data = sample.read_bytes()
    sample_sha = hashlib.sha256(sample_data).hexdigest()

    results = {
        "meta": {
            "sample": str(sample),
            "sample_sha256": sample_sha,
            "sample_size": len(sample_data),
            "operator_run": utc_now(),
        },
        "operators": {
            "imports": operator_imports(sample),
            "byte_grep": operator_byte_grep(sample),
            "capstone": operator_capstone_entry(sample),
            "strings": operator_strings(sample),
            "anti_analysis": operator_anti_analysis(sample),
        },
    }

    if args.dry_run:
        print("DRY_RUN: would write fact bundle with:")
        for k, v in results["operators"].items():
            print(f"  {k}: {v.get('status', '?')}")
        return 0

    fact_path = write_fact(workspace, sample, results)
    print(f"OK: wrote {fact_path}")

    failed = sum(1 for v in results["operators"].values() if v.get("status") not in ("ok", "skipped"))
    if failed > 0:
        print(f"WARN: {failed} operator(s) failed; fact file may be partial")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())