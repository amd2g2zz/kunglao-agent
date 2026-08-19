# -*- coding: utf-8 -*-
"""tests/test_rust_dep_strings.py — issue #427 tools/static/rust-dep-strings contract.

Dual-channel Rust crate dependency-string carving:
  registry channel — cargo registry paths (`registry/(src|cache|index)/<host>-<16hex>/...`),
                     bare registry ids, `registry+<scheme>://` source URLs;
  crate channel    — standalone `<crate-name>-<semver>` byte strings.

Covers per cli-script-checklist (#277): --help renders, parameterized input
via tmp files, three-state exit codes (0 ok / 1 negative / 2 error),
--reproduce field=value lines (kunglao L1 mechanical-gate format), --json
single-object output. Fixtures are SYNTHETIC (no real-sample bytes); the
plain-binary fixture pins the zero-false-positive acceptance item.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "static" / "rust-dep-strings.py"

# Matches scripts/kunglao_verify.py _ACTUAL_ASSERTION_RE (L1 field=value parser).
L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")

CRATES_IO_SPARSE = b"index.crates.io-6f17d22bba15001f"
CRATES_IO_GIT = b"github.com-1ecc6299db9ec823"


def run_cli(*args):
    # RED-state guard: before the tool exists, return a completed-process
    # stand-in so assertions FAIL (not error) — the plan requires red tests
    # to be "test failed", never a collection/spawn error.
    if not TOOL.exists():
        return subprocess.CompletedProcess(
            list(args), 127, "", f"tool not implemented yet: {TOOL}")
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )


def parse_reproduce(stdout):
    return dict(L1_LINE_RE.match(line).groups() for line in stdout.splitlines()
                if L1_LINE_RE.match(line))


def write_tmp(tmp_path, name, content):
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ---------------------------------------------------------------------------
# Synthetic fixtures (no real samples — issue hard constraint)
# ---------------------------------------------------------------------------

POSITIVE = (
    b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 +
    # registry src, forward separators, sparse crates.io id
    b"/root/.cargo/registry/src/" + CRATES_IO_SPARSE +
    b"/serde-1.0.193/src/lib.rs\x00" +
    # registry src, backslash separators, git-registry id (C:\home builder —
    # a home-dir shape that carries no personal-username component)
    b"C:\\home\\builder\\.cargo\\registry\\src\\" + CRATES_IO_GIT +
    b"\\rand-0.8.5\\src\\rng.rs\x00" +
    # registry cache kind with .crate archive suffix
    b".cargo/registry/cache/" + CRATES_IO_SPARSE + b"/libc-0.2.151.crate\x00" +
    # prerelease version tail survives the backtrack extraction
    b"registry/src/" + CRATES_IO_SPARSE +
    b"/rand_core-0.9.0-alpha.1/src/lib.rs\x00" +
    # standalone crate string (panic-metadata style) + a serde duplicate so
    # the merged row carries BOTH channels
    b"panicked at src/main.rs:12:5\x00tokio-1.35.1\x00serde-1.0.193\x00" +
    # cargo SourceId replacement URL
    b"registry+https://github.com/rust-lang/crates.io-index\x00"
)

# A registry path whose tail has no <name>-<semver> component must NOT yield
# a crate row (backtrack rejection) — but the registry id is still evidence.
NO_VERSION_TAIL = (
    b"\x7fELF\x02\x01\x01\x00" +
    b"registry/src/" + CRATES_IO_SPARSE + b"/AAAABBBBCCCC\x00"
)

# Plain non-Rust binary: DOS stub + import-ish strings + a registry-like
# word WITHOUT cargo structure. Zero hits is the acceptance item.
PLAIN_BINARY = (
    b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" +
    b"This program cannot be run in DOS mode.\r\r\n$" +
    b"KERNEL32.DLL\x00GetProcAddress\x00CreateFileW\x00" +
    b"Microsoft Visual C++ Runtime\x00" +
    b"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run\x00" +
    b"http://update.example.com/config\x00"
)

# M1 pin (review fixture): cache archive with a PRERELEASE version — cargo
# cache filenames are exactly `<crate>-<version>.crate`, and the greedy
# prerelease charset must not swallow the archive suffix into the version.
CACHE_PRERELEASE = (
    b"\x7fELF\x02\x01\x01\x00" +
    b"registry/cache/" + CRATES_IO_SPARSE + b"/mytool-1.2.3-beta.1.crate\x00"
)

# Same crate+version through BOTH registry sub-kinds (src path + cache
# archive): the (name, version) key must merge them into ONE row.
SRC_CACHE_MERGE = (
    b"\x7fELF\x02\x01\x01\x00" +
    b"registry/src/" + CRATES_IO_SPARSE +
    b"/rand_core-0.9.0-alpha.1/src/lib.rs\x00" +
    b".cargo/registry/cache/" + CRATES_IO_SPARSE +
    b"/rand_core-0.9.0-alpha.1.crate\x00"
)

# M2 pin (fault-inject #427 R2): the cache `.crate` strip removes exactly
# one literal suffix, never a charset rstrip — cache versions whose LEGAL
# tail sits inside the {. c r a t e} charset (`2.0.0-release` ends in `e`,
# `1.2.3-beta.` ends in `.`) must survive intact.
CACHE_SUFFIX_BOUNDARY = (
    b"\x7fELF\x02\x01\x01\x00" +
    b"registry/cache/" + CRATES_IO_SPARSE + b"/mytool-2.0.0-release.crate\x00" +
    b"registry/cache/" + CRATES_IO_SPARSE + b"/mytool-1.2.3-beta.\x00"
)

# M4 pin (fault-inject #427 R2): a dotted-host token whose hex tail is NOT
# 16 chars is not a cargo registry id — the 16-hex length is part of the id
# contract (16-hex positive control: CRATES_IO_SPARSE inside POSITIVE).
NON16HEX_TOKEN = (
    b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" +
    b"This program cannot be run in DOS mode.\r\r\n$" +
    b"KERNEL32.DLL\x00" +
    b"example.com-1a2b3c4d\x00" +
    b"http://example.com/1a2b3c4d/config\x00"
)

# M7 pin (fault-inject #427 R2): same crate NAME at two different VERSIONS
# — the merge key is (name, version), never name-only.
SAME_NAME_TWO_VERSIONS = (
    b"\x7fELF\x02\x01\x01\x00" +
    b"registry/src/" + CRATES_IO_SPARSE + b"/serde-1.0.193/src/lib.rs\x00" +
    b"serde-1.0.150\x00"
)


# ---------------------------------------------------------------------------
# CLI contract (#277 checklist: help / errors / negative)
# ---------------------------------------------------------------------------

def test_help_exit_zero():
    r = run_cli("--help")
    assert r.returncode == 0, f"exit {r.returncode}, stderr={r.stderr[:200]}"
    assert "usage" in r.stdout.lower()


def test_missing_input_exit_2():
    r = run_cli()
    assert r.returncode == 2, f"exit {r.returncode}, stdout={r.stdout[:200]}"
    err = json.loads(r.stderr)
    assert err["exit_code"] == 2
    assert "--in" in err["error"]


def test_unreadable_input_exit_2():
    r = run_cli("--in", "no-such-file.bin")
    assert r.returncode == 2, f"exit {r.returncode}, stdout={r.stdout[:200]}"
    err = json.loads(r.stderr)
    assert err["exit_code"] == 2
    assert "check the path" in err["error"]


def test_empty_input_exit_1_json(tmp_path):
    p = write_tmp(tmp_path, "empty.bin", b"")
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 1, f"exit {r.returncode}, stdout={r.stdout[:200]}"
    data = json.loads(r.stdout)
    assert data["tool"] == "rust-dep-strings"
    assert data["status"] == "NEGATIVE"


def test_empty_input_exit_1_reproduce(tmp_path):
    p = write_tmp(tmp_path, "empty.bin", b"")
    r = run_cli("--in", str(p), "--reproduce")
    assert r.returncode == 1, f"exit {r.returncode}, stdout={r.stdout[:200]}"
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == "rust-dep-strings"
    assert fields["status"] == "NEGATIVE"


def test_bad_channel_value_exit_2(tmp_path):
    p = write_tmp(tmp_path, "x.bin", POSITIVE)
    r = run_cli("--in", str(p), "--channels", "bogus")
    assert r.returncode == 2
    err = json.loads(r.stderr)
    assert "channels" in err["error"]


# ---------------------------------------------------------------------------
# registry channel
# ---------------------------------------------------------------------------

def _crates_of(r):
    return json.loads(r.stdout)["crates"]


def test_registry_src_path_forward_slash(tmp_path):
    p = write_tmp(tmp_path, "rust1.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = {(c["crate"], c["version"]): c for c in _crates_of(r)}
    row = rows[("serde", "1.0.193")]
    assert "registry" in row["channels"]
    assert row["registry"] == CRATES_IO_SPARSE.decode()
    assert row["path_kind"] == "src"


def test_registry_src_path_backslash_variant(tmp_path):
    p = write_tmp(tmp_path, "rust2.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = {(c["crate"], c["version"]): c for c in _crates_of(r)}
    row = rows[("rand", "0.8.5")]
    assert row["registry"] == CRATES_IO_GIT.decode()


def test_registry_cache_crate_suffix(tmp_path):
    p = write_tmp(tmp_path, "rust3.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = {(c["crate"], c["version"]): c for c in _crates_of(r)}
    row = rows[("libc", "0.2.151")]
    assert row["path_kind"] == "cache"


def test_prerelease_version_tail_kept(tmp_path):
    p = write_tmp(tmp_path, "rust4.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    names = {(c["crate"], c["version"]) for c in _crates_of(r)}
    assert ("rand_core", "0.9.0-alpha.1") in names


def test_registry_cache_prerelease_strips_crate_suffix(tmp_path):
    # M1 pin (review fixture `registry/cache/<id>/mytool-1.2.3-beta.1.crate`):
    # on every output face the version is 1.2.3-beta.1 — the `.crate` archive
    # suffix never leaks into it. Combined matrix cell: cache kind (plain
    # version pinned above) x prerelease tail (src kind pinned above).
    p = write_tmp(tmp_path, "cachepre.bin", CACHE_PRERELEASE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = _crates_of(r)
    assert [(c["crate"], c["version"]) for c in rows] == \
        [("mytool", "1.2.3-beta.1")]
    assert rows[0]["path_kind"] == "cache"
    r = run_cli("--in", str(p))  # text face
    assert "crate=mytool version=1.2.3-beta.1 " in r.stdout
    assert "version=1.2.3-beta.1.crate" not in r.stdout
    r = run_cli("--in", str(p), "--reproduce")  # reproduce face
    fields = parse_reproduce(r.stdout)
    assert fields["first_version"] == "1.2.3-beta.1"


def test_cache_suffix_strip_is_literal_not_charset(tmp_path):
    # M2 pin (fault-inject #427 R2, mutation: the `.crate` strip turned into
    # a greedy charset rstrip): the strip removes exactly ONE literal suffix.
    # Legal version tails inside the {. c r a t e} charset — `2.0.0-release`
    # ends in `e`, `1.2.3-beta.` ends in `.` — must survive intact
    # (a charset rstrip would yield `2.0.0-releas` / `1.2.3-b`).
    p = write_tmp(tmp_path, "cacheedge.bin", CACHE_SUFFIX_BOUNDARY)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = {(c["crate"], c["version"]) for c in _crates_of(r)}
    assert rows == {("mytool", "2.0.0-release"), ("mytool", "1.2.3-beta.")}
    r = run_cli("--in", str(p))  # text face
    assert "crate=mytool version=2.0.0-release " in r.stdout
    assert "crate=mytool version=1.2.3-beta. " in r.stdout


def test_src_and_cache_merge_on_same_name_version(tmp_path):
    # M1 downstream pin: before the suffix fix the cache key was
    # `0.9.0-alpha.1.crate` and split the same crate into two rows.
    p = write_tmp(tmp_path, "merge.bin", SRC_CACHE_MERGE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = _crates_of(r)
    assert len(rows) == 1  # (name, version) key merges src + cache hits
    row = rows[0]
    assert (row["crate"], row["version"]) == ("rand_core", "0.9.0-alpha.1")
    assert len(row["offsets"]) == 2  # both byte positions on the one row


def test_same_name_two_versions_stay_two_rows(tmp_path):
    # M7 pin (fault-inject #427 R2, mutation: merge key (name, version) ->
    # name-only): `serde-1.0.193` (registry src path) and `serde-1.0.150`
    # (standalone crate string) share a NAME but not a version — both rows
    # must survive (a name-only key would swallow the 1.0.150 row).
    p = write_tmp(tmp_path, "twovers.bin", SAME_NAME_TWO_VERSIONS)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = _crates_of(r)
    assert len(rows) == 2
    assert {(c["crate"], c["version"]) for c in rows} == \
        {("serde", "1.0.193"), ("serde", "1.0.150")}


def test_registry_ids_listed(tmp_path):
    p = write_tmp(tmp_path, "rust5.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    ids = {e["id"] for e in json.loads(r.stdout)["registry_ids"]}
    assert CRATES_IO_SPARSE.decode() in ids
    assert CRATES_IO_GIT.decode() in ids


def test_registry_source_url(tmp_path):
    p = write_tmp(tmp_path, "rust6.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    urls = [e["url"] for e in json.loads(r.stdout)["registry_sources"]]
    assert any(u == "registry+https://github.com/rust-lang/crates.io-index"
               for u in urls)


def test_registry_path_without_version_yields_no_crate(tmp_path):
    p = write_tmp(tmp_path, "noversion.bin", NO_VERSION_TAIL)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr  # registry id alone is Rust evidence
    out = json.loads(r.stdout)
    assert out["crates"] == []
    ids = {e["id"] for e in out["registry_ids"]}
    assert CRATES_IO_SPARSE.decode() in ids


# ---------------------------------------------------------------------------
# crate channel + channel merge / filter
# ---------------------------------------------------------------------------

def test_standalone_crate_channel(tmp_path):
    p = write_tmp(tmp_path, "rust7.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = {(c["crate"], c["version"]): c for c in _crates_of(r)}
    row = rows[("tokio", "1.35.1")]
    assert row["channels"] == ["crate"]
    assert row["registry"] is None


def test_both_channels_merge_on_same_crate(tmp_path):
    p = write_tmp(tmp_path, "rust8.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = {(c["crate"], c["version"]): c for c in _crates_of(r)}
    assert rows[("serde", "1.0.193")]["channels"] == ["registry", "crate"]


def test_channels_filter_registry_only(tmp_path):
    p = write_tmp(tmp_path, "rust9.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json", "--channels", "registry")
    assert r.returncode == 0, r.stderr
    names = {c["crate"] for c in _crates_of(r)}
    assert "tokio" not in names      # standalone string not scanned
    assert "serde" in names          # path-derived row survives


def test_channels_filter_crate_only(tmp_path):
    p = write_tmp(tmp_path, "rust10.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json", "--channels", "crate")
    assert r.returncode == 0, r.stderr
    names = {c["crate"] for c in _crates_of(r)}
    assert names == {"tokio", "serde"}   # libc/rand/rand_core were path-only


def test_channels_duplicate_values_dedup(tmp_path):
    # N1 pin: `--channels registry,registry` is valid but must scan the
    # channel once and echo it once — no duplicate values in the JSON face.
    p = write_tmp(tmp_path, "dupchan.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json", "--channels", "registry,registry")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["channels"] == ["registry"]
    names = {c["crate"] for c in out["crates"]}
    assert "tokio" not in names      # duplicate spec still filters, not widens
    assert "serde" in names


# ---------------------------------------------------------------------------
# zero false positives on a plain binary (issue acceptance)
# ---------------------------------------------------------------------------

def test_plain_binary_negative(tmp_path):
    p = write_tmp(tmp_path, "plain.bin", PLAIN_BINARY)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 1, f"exit {r.returncode}, stdout={r.stdout[:400]}"
    out = json.loads(r.stdout)
    assert out["status"] == "NEGATIVE"
    assert out.get("total", 0) == 0


def test_dotted_host_non16hex_token_is_not_registry_id(tmp_path):
    # M4 pin (fault-inject #427 R2, mutation: registry-id `16hex` length
    # relaxed to `[a-f0-9]+`): a dotted-host token with an 8-hex tail
    # (`example.com-1a2b3c4d`) is NOT cargo registry evidence — 16 hex
    # chars is part of the id contract (positive control: the 16-hex ids
    # inside POSITIVE).
    p = write_tmp(tmp_path, "hex8.bin", NON16HEX_TOKEN)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 1, f"exit {r.returncode}, stdout={r.stdout[:400]}"
    out = json.loads(r.stdout)
    assert out["status"] == "NEGATIVE"
    assert out.get("total", 0) == 0


# ---------------------------------------------------------------------------
# output faces: --json single object, --reproduce L1 rows, text default
# ---------------------------------------------------------------------------

def test_json_single_object_stable_keys(tmp_path):
    p = write_tmp(tmp_path, "rust11.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)  # whole stdout is exactly one JSON object
    for key in ("tool", "input_sha256", "channels", "total", "crates",
                "registry_ids", "registry_sources"):
        assert key in out, f"missing key {key!r}"
    assert out["tool"] == "rust-dep-strings"
    assert out["total"] == len(out["crates"])
    row = out["crates"][0]
    for key in ("crate", "version", "channels", "offsets", "offsets_capped",
                "registry", "path_kind"):
        assert key in row, f"missing crate-row key {key!r}"


def test_reproduce_l1_rows(tmp_path):
    p = write_tmp(tmp_path, "rust12.bin", POSITIVE)
    r = run_cli("--in", str(p), "--reproduce")
    assert r.returncode == 0, r.stderr
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == "rust-dep-strings"
    assert re.fullmatch(r"[0-9a-f]{64}", fields["input_sha256"])
    assert int(fields["total"]) == 5
    assert fields["first_crate"] == "serde"
    assert fields["first_version"] == "1.0.193"
    assert fields["first_channel"] == "registry"


def test_text_default_one_line_per_crate(tmp_path):
    p = write_tmp(tmp_path, "rust13.bin", POSITIVE)
    r = run_cli("--in", str(p))
    assert r.returncode == 0, r.stderr
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 5
    assert all(ln.startswith("off=0x") for ln in lines)
    joined = r.stdout
    assert "crate=serde version=1.0.193" in joined
    assert "crate=rand_core version=0.9.0-alpha.1" in joined
    assert "channels=registry,crate" in joined


def test_offsets_are_real_byte_offsets(tmp_path):
    # The reported offset is the structural marker position (`registry/src/`
    # + registry id) in the RAW byte buffer — a byte-window scan, not a
    # printable-filtered reconstruction (the absorbed script's flaw).
    p = write_tmp(tmp_path, "rust14.bin", POSITIVE)
    r = run_cli("--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    rows = {(c["crate"], c["version"]): c for c in _crates_of(r)}
    real = POSITIVE.find(b"registry/src/" + CRATES_IO_SPARSE)
    assert rows[("serde", "1.0.193")]["offsets"][0] == real
