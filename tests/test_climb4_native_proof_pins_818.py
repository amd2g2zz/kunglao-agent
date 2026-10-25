#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_native_proof_pins_818.py — #818 climb segment 4C.

Behavior pins on REAL synthetic binaries for the eval_native_targets
proof faces that need no toolchain (the segment-3 lesson: the NDK/go/upx
build faces stay honest skips in their absence — these pins cover what
removes "the artifact was never parsed" from the blind spot):

  the ELF64 .text readers over a hand-minted section-header image
  (addr/offset/size extraction, symbol-table walk with the
  function-symbol filter, the not-found refusals), the PE32+ .text
  VirtualSize reader (signature + section-miss refusals), the constant
  scanner's four encoding forms, and the toolchain discovery faces over
  an env SANDBOX (only the dict's HOME/PATH consulted: highest-API NDK
  wrapper wins, unnumbered fallback, exec-bit enforcement, the
  toolchain_report row statuses mirroring the sandbox).
"""
from __future__ import annotations

import stat
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_native_targets as ent  # noqa: E402


# ------------------------------------------------------------ ELF mint

def _mk_elf64(*, text_addr=0x6000, text_bytes=b"\x90" * 0x20,
              symbols=None, with_text=True) -> bytes:
    """A minimal but well-formed 64-bit little-endian ELF image:
    ehdr | .text | .symtab | .strtab | .shstrtab | section headers.
    symbols: [(name, st_info, st_value, st_size)]."""
    shstrtab = b"\x00.text\x00.symtab\x00.strtab\x00"
    name_text, name_sym, name_str = 1, 7, 15
    names = [s[0] for s in (symbols or [])]
    strtab = b"\x00" + b"".join(n.encode() + b"\x00" for n in names)
    entries = [b"\x00" * 24]  # the null symbol every symtab carries
    for nm, info, val, sz in (symbols or []):
        entries.append(struct.pack("<IBBHQQ", strtab.index(nm.encode()),
                                   info, 0, 1, val, sz))
    symtab = b"".join(entries)

    text_off = 64
    symtab_off = text_off + len(text_bytes)
    strtab_off = symtab_off + len(symtab)
    shstr_off = strtab_off + len(strtab)
    shoff = shstr_off + len(shstrtab)

    def shdr(name, typ, addr, off, size, link=0, entsize=0):
        return struct.pack("<IIQQQQIIQQ", name, typ, 0, addr, off, size,
                           link, 0, 1, entsize)

    headers = shdr(0, 0, 0, 0, 0)                       # SHT_NULL
    headers += shdr(name_text, 1, text_addr, text_off,
                    len(text_bytes) if with_text else 0)  # PROGBITS
    headers += shdr(name_sym, 2, 0, symtab_off, len(symtab),
                    link=3, entsize=24)                  # SYMTAB -> strtab
    headers += shdr(name_str, 3, 0, strtab_off, len(strtab))  # STRTAB
    headers += shdr(0, 3, 0, shstr_off, len(shstrtab))   # SHSTRTAB

    ehdr = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    ehdr += struct.pack("<HHIQQQIHHHHHH", 2, 0xB7, 1, 0, 0, shoff, 0,
                        64, 0, 0, 64, 5, 4)
    assert len(ehdr) == 64
    blob = bytearray(ehdr + text_bytes + symtab + strtab + shstrtab
                     + headers)
    # the .text file offset must match what the header declares
    assert len(blob) > text_off + len(text_bytes)
    return bytes(blob)


def _mk_pe64(*, text_vsize=0x30, section_name=b".text\x00\x00\x00",
             nsec=1, sig=b"PE\x00\x00") -> bytes:
    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    coff = struct.pack("<HHIIIHH", 0x8664, nsec, 0, 0, 0, 240, 0x22)
    sections = b""
    for i in range(nsec):
        nm = section_name if i == 0 else b".rdata\x00\x00"
        sections += struct.pack("<8sIIIIIIHHI", nm,
                                text_vsize if i == 0 else 0x10,
                                0x1000 + i * 0x1000, 0x200, 0x400, 0, 0,
                                0, 0, 0x60000020)
    return bytes(dos) + sig + coff + b"\x00" * 240 + sections


# ------------------------------------------------------- ELF64 readers

class TestElfReaders:
    def test_text_section_reader_returns_addr_and_offset(self) -> None:
        blob = _mk_elf64(text_addr=0x6000)
        assert ent._elf_text_section(blob) == (0x6000, 64)
        assert ent.elf_text_size(blob) == 0x20

    def test_missing_text_section_refuses(self) -> None:
        # rename the section inside the string table (same-length swap so
        # the fixed shstrtab size stays true): same image shape, but no
        # section answers to ".text" any more
        stripped = _mk_elf64().replace(b"\x00.text\x00", b"\x00text2\x00",
                                       1)
        with pytest.raises(RuntimeError, match="not found"):
            ent.elf_text_size(stripped)
        with pytest.raises(RuntimeError, match="not found"):
            ent._elf_text_section(stripped)

    def test_symbol_walk_filters_to_defined_functions(self) -> None:
        symbols = [("real_fn", 0x12, 0x6000, 0x40),   # GLOBAL|FUNC
                   ("a_data", 0x11, 0x8000, 0x10),    # GLOBAL|OBJECT — skip
                   ("local_fn", 0x02, 0x6100, 0x20),  # LOCAL|FUNC — still ok
                   ("sized_zero", 0x12, 0x6200, 0x0)]  # zero size — skip
        blob = _mk_elf64(symbols=symbols)
        assert ent._symbol_vaddr(blob, "real_fn") == (0x6000, 0x40)
        assert ent._symbol_vaddr(blob, "local_fn") == (0x6100, 0x20)
        # a data symbol never satisfies the function-symbol contract
        data_blob = _mk_elf64(symbols=[("data_only", 0x11, 8, 8)])
        with pytest.raises(RuntimeError, match="not found"):
            ent._symbol_vaddr(data_blob, "data_only")
        with pytest.raises(RuntimeError):
            ent._symbol_vaddr(blob, "no_such_symbol")


# -------------------------------------------------------- PE32+ reader

class TestPeReader:
    def test_text_virtual_size_reads_from_the_section_table(self) -> None:
        assert ent.pe_text_size(_mk_pe64(text_vsize=0x37)) == 0x37

    def test_bad_signature_refuses(self) -> None:
        with pytest.raises(RuntimeError, match="signature"):
            ent.pe_text_size(_mk_pe64(sig=b"LE\x00\x00"))

    def test_missing_text_section_refuses(self) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            ent.pe_text_size(_mk_pe64(section_name=b".data\x00\x00\x00"))


# ---------------------------------------------------- constant scanner

class TestConstantScanner:
    def test_all_four_encoding_forms_are_detected(self) -> None:
        v = 0xDEADBEEF
        blob = (f"{v:08x}".encode() + b"|"
                + f"{v:016x}".encode() + b"|"
                + str(v).encode() + b"|"
                + (v & 0xFFFFFFFF).to_bytes(4, "little"))
        hits = ent._scan_constants(blob, {"k0": v})
        assert hits == {"k0": True}

    def test_a_single_form_is_enough_and_absence_is_reported(self) -> None:
        blob = b"only the decimal form: 3735928559 and noise"
        hits = ent._scan_constants(blob, {"present": 0xDEADBEEF,
                                          "absent": 0x0BADF00D})
        assert hits["present"] is True
        assert hits["absent"] is False


# -------------------------------------------- toolchain sandbox faces

class TestToolchainSandbox:
    def test_env_dict_is_a_sandbox_not_the_host(self, tmp_path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        assert ent._env_home({"HOME": str(home)}) == home
        assert ent._env_home({}) is None
        # the explicit-dict contract: only the dict is consulted
        assert ent.find_ndk_clang({"HOME": str(home), "PATH": ""}) is None

    def test_which_enforces_the_exec_bit_inside_the_sandbox(
            self, tmp_path) -> None:
        bin_d = tmp_path / "bin"
        bin_d.mkdir()
        live = bin_d / "go"
        live.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        live.chmod(0o755)
        dead = bin_d / "upx"
        dead.write_text("not executable", encoding="utf-8")
        env = {"PATH": str(bin_d), "HOME": ""}
        assert ent._which("go", env) == str(live)
        assert ent._which("upx", env) is None
        assert ent._which("never-here", env) is None

    def _ndk_home(self, tmp_path: Path, apis: tuple[int, ...] = (),
                  plain: bool = False) -> Path:
        ndk_bin = tmp_path / ".NDK" / "arm64" / "bin"
        ndk_bin.mkdir(parents=True)
        for api in apis:
            (ndk_bin / f"aarch64-linux-android{api}-clang").write_text(
                "#!/bin/sh\n", encoding="utf-8")
        if plain:
            (ndk_bin / "aarch64-linux-android-clang").write_text(
                "#!/bin/sh\n", encoding="utf-8")
        return tmp_path

    def test_highest_api_wrapper_wins(self, tmp_path) -> None:
        home = self._ndk_home(tmp_path, apis=(24, 26, 30))
        env = {"HOME": str(home), "PATH": ""}
        got = ent.find_ndk_clang(env)
        assert got is not None
        assert got.endswith("aarch64-linux-android30-clang")

    def test_unnumbered_wrapper_is_the_fallback(self, tmp_path) -> None:
        home = self._ndk_home(tmp_path, plain=True)
        got = ent.find_ndk_clang({"HOME": str(home), "PATH": ""})
        assert got is not None
        assert got.endswith("aarch64-linux-android-clang")

    def test_absent_ndk_home_reads_none(self, tmp_path) -> None:
        env = {"HOME": str(tmp_path / "empty-home"), "PATH": ""}
        assert ent.find_ndk_clang(env) is None
        assert ent.find_ndk_clang({"PATH": ""}) is None

    def test_lld_and_strip_prefer_the_sandbox_path(self, tmp_path) -> None:
        bin_d = tmp_path / "bin"
        bin_d.mkdir()
        for name in ("ld.lld", "llvm-strip", "strip"):
            p = bin_d / name
            p.write_text("#!/bin/sh\n", encoding="utf-8")
            p.chmod(0o755)
        env = {"PATH": str(bin_d), "HOME": ""}
        assert ent.find_lld(env) == str(bin_d / "ld.lld")
        # llvm-strip is preferred over plain strip when both exist
        assert ent.find_strip(env) == str(bin_d / "llvm-strip")

    def test_strip_falls_back_to_plain_strip(self, tmp_path) -> None:
        bin_d = tmp_path / "bin"
        bin_d.mkdir()
        p = bin_d / "strip"
        p.write_text("#!/bin/sh\n", encoding="utf-8")
        p.chmod(stat.S_IRUSR | stat.S_IXUSR)
        env = {"PATH": str(bin_d), "HOME": ""}
        assert ent.find_strip(env) == str(bin_d / "strip")

    def test_report_rows_mirror_the_sandbox(self, tmp_path) -> None:
        bin_d = tmp_path / "bin"
        bin_d.mkdir()
        go = bin_d / "go"
        go.write_text("#!/bin/sh\n", encoding="utf-8")
        go.chmod(0o755)
        home = self._ndk_home(tmp_path, apis=(28,))
        rows = {r["toolchain"]: r
                for r in ent.toolchain_report({"PATH": str(bin_d),
                                               "HOME": str(home)})}
        assert rows["ndk-arm64"]["status"] == "OK"
        assert rows["ndk-arm64"]["path"].endswith("android28-clang")
        assert rows["go"]["status"] == "OK"
        assert rows["upx"]["status"] == "TOOLCHAIN_MISSING"
        assert rows["upx"]["path"] == ""
        assert rows["ld.lld"]["status"] == "TOOLCHAIN_MISSING"
        assert set(rows) == {"ndk-arm64", "go", "upx", "clang", "ld.lld",
                             "llvm-strip"}
