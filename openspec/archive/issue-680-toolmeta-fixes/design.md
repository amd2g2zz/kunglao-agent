# Design — toolchain.FIXES → structured ToolMeta (#680)

## D1. ToolMeta schema

```python
@dataclass(frozen=True)
class ToolMeta:
    fix: str                        # remediation guidance (the legacy FIXES string, verbatim)
    description: str                # one-line purpose
    url: str | None                 # official homepage/docs (None = unknown → fallback render)
    repo: str | None = None         # source repository
    package: str | None = None      # PyPI/npm/apt package name
    verify_cmd: str | None = None   # post-install verify command (jadx --version)

    def __str__(self) -> str:       # backward compat: renders as the fix text
        return self.fix
```

`fix` and `description` are required positionals; `url` is required-typed but nullable
(static entries always populate it — RED2 pins that; `mcp:*` entries are None — RED4 pins
the fallback). `repo`/`package`/`verify_cmd` default None. Immutable (frozen), same as
`NextAction`.

Why `fix` stays a field rather than being deleted: `format_human`, `format_json`, the
init refusal, negotiation menu, and deploy_shim all render the remediation prose, and
`tests/test_toolchain.py` pins `fix` as a truthy str containing the tool name. The issue
adds metadata fields around the guidance; it does not remove the guidance.

## D2. Backward compatibility (two layers)

1. **Typed face**: `toolchain.fix_text(name: str) -> str | None` — the canonical string
   accessor. All in-repo callers (`kunglao-init`, `toolchain_negotiation`, `deploy_shim`,
   `toolchain_install`) are updated to it (issue: "old string callers updated").
2. **Degraded face**: `ToolMeta.__str__` returns `self.fix` — an out-of-repo caller (user
   script, other agent code) doing `f"{toolchain.FIXES[name]}"` renders the legacy
   guidance text, never a dataclass repr. RED5 pins this contract.

`.get(name, default)` callers keep their default semantics by `fix_text(name) or default`
— identical behavior for unknown names (None → default) and known names (fix text).

## D3. mcp:* derived entries (out of scope, fallback path)

```python
FIXES.update({
    f"mcp:{i.name}": ToolMeta(fix=i.register, description=i.purpose, url=None)
    for i in mcp_probe.MANIFEST
})
```

Issue #680 declares MCP server metadata out of scope (separate manifest). The derived
entries keep the register-command-as-fix semantics and gain `description` for free from
`MCPItem.purpose`. `url=None` exercises the fallback rendering — exactly the RED4 path.

## D4. URL data policy (no fabrication)

- Issue-given (authoritative): apkid → https://github.com/rednaga/APKiD,
  baksmali → https://github.com/baksmali/smali/releases.
- Official upstreams (high confidence): ghidra → https://ghidra-sre.org/ +
  repo https://github.com/NationalSecurityAgency/ghidra; jadx →
  https://github.com/skylot/jadx; apktool → https://github.com/iBotPeaches/Apktool;
  floss → https://github.com/mandiant/flare-floss; die →
  https://github.com/horsicq/Detect-It-Easy; pefile →
  https://github.com/erocarrera/pefile; binutils family (readelf/objdump) →
  https://www.gnu.org/software/binutils/; file → https://www.darwinsys.com/file/;
  IDA → https://hex-rays.com/ida-pro/; frida → https://frida.re/ +
  https://github.com/frida/frida; Magisk → https://github.com/topjohnwu/Magisk;
  Android SDK tools (adb/aapt/debug_flag docs) → https://developer.android.com/tools/…;
  JDWP spec → https://docs.oracle.com/javase/8/docs/technotes/guides/jpda/jdwp-spec.html.
- Distribution pages where they are the official source: gitnexus →
  https://www.npmjs.com/package/gitnexus (the `npm i -g gitnexus` origin; no other
  canonical homepage known — not fabricated).
- Project-internal channel checks (vm_reachable, remote_debugger) are not upstream
  tools; their "docs URL" is this repo (https://github.com/amd2g2zz/kunglao-agent) —
  the vmr-shell/VM-channel contract lives there.
- Anything uncertain → `url=None` + fallback rendering, never a guessed URL.

## D5. Rendering contract (URL on its own line)

`format_human` non-PASS item block becomes:

```
  [FAIL] [HARD] jadx: not found in PATH
      fix: install jadx and add it to PATH
      url: https://github.com/skylot/jadx
      verify: jadx --version
      action: install
```

`url:` renders only when known (fallback omits the line — RED4); `verify:` only when
present. `format_json` keeps `"fix"` as the text string (schema stability —
test_toolchain.py pins it) and adds `"fix_url"` (additive). `kunglao-init.py`
`refuse_toolchain` mirrors the same lines: `fix:` then `url:` on its own line.

## D6. toolchain_install.py reads structured fields

- `_official_guidance(name)` → `toolchain.fix_text(name) or "see the toolchain check
  detail above"` (unchanged default).
- Install-failure guidance (`ask_then_install` failure branch) appends `url:` and
  `verify:` lines read from the ToolMeta — the operator gets the upstream address and
  the verify command exactly where the failure is reported.
- `_run_install_plan` success path prints the verify command before re-probe ("verify:
  jadx --version") so the operator can confirm beyond the re-probe.

## D7. Test strategy (RED-first, 5 cases per issue acceptance)

- RED1 schema shape: ToolMeta has exactly the 6 fields; FIXES values are ToolMeta
  instances; every static entry's fix is a non-empty str.
- RED2 url coverage: all 23 static (non-`mcp:`) entries have non-None, http(s) url and
  non-empty description.
- RED3 verify_cmd: every FIXES key that is install-able
  (`toolchain_install.INSTALL_PLANS[name].kind == "auto"`) has a verify_cmd.
- RED4 fallback: an entry with url=None (the `mcp:ghidra` entry) renders without the
  `url:` line and without crashing; unknown name → `fix_text` returns None and
  `FIXES.get` default semantics hold.
- RED5 backward compat: `str(FIXES["pefile"])` == `fix_text("pefile")` == the legacy
  guidance; the guidance contains "pip install pefile".

## D8. Risks

- JSON consumers expecting `"fix"` unchanged: covered (fix stays str; only additive
  `fix_url`).
- Tests iterating `for name in tc.FIXES` (keys): unaffected by the value type change.
- `next_action_for` mcp branch passed the whole ToolMeta into `NextAction.command` if
  missed — updated to `meta.fix` and pinned by the existing
  `test_every_fixes_fail_name_derives_next_action` (command must be str).
