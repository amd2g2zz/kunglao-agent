# Design — write_guard payload decode must never silently allow (#686)

## D1. Root cause chain (measured)

Reproduction (exact harness conditions of `tests/test_write_guard_532.py::
_run_guard`, child = venv python running the guard, parent encodes stdin with
the host locale):

```
[pytest-probe] rc=1
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa1 in position 1032: invalid start byte
  File "...wg686_child.py", line 15, in <module>
    raw = sys.stdin.read()
```

1. Payload JSON is built with `json.dumps(..., ensure_ascii=False)`; the
   fact/note bodies contain U+2014 EM DASH.
2. Parent (`subprocess.run(..., input=payload, text=True)`) encodes stdin with
   `locale.getpreferredencoding()` == `cp936` on the failing Windows host →
   em-dash becomes `0xA1 0xAA`.
3. Child has `PYTHONIOENCODING=utf-8` (harness and Claude Code convention) →
   the text layer decodes stdin as UTF-8 → `0xA1` is an invalid start byte.
4. `_read_payload()` wraps `sys.stdin.read()` in `except Exception: return {}`
   → the decode crash is indistinguishable from "no payload".
5. `main()`: `ti = payload.get("tool_input") or {}` → `{}`;
   `raw_target = ti.get("file_path")` → `None` → `return RC_ALLOW` — before
   `resolve_workspace`, before `carrier_of`, before `adjudicate`.

Rule legs measured working in-process on the same host (all 7 shapes):
`lint_facts.lint_workspace` (BAD_STATUS on W-2 shape), `write_gate.audit_workspace`
(R1 self-stamp + W2 attributions), `notes_writer.check_write` (chainless /
inherited / fake-chain), `lib_kunglao.resolve_workspace` (analysis_state.txt
markers), and the write_guard local walk fallback.

Why Linux CI stayed green: POSIX hosts default to a UTF-8 locale, so parent
and child agree on the encoding and the mismatch never fires. This is a
Windows/GBK-only silent failure — the second of the two suspects named in the
batch plan ("GBK 解码路径"), not the posix-separator one.

## D2. The decode chain

```python
def _read_payload() -> dict:
    try:
        buf = getattr(sys.stdin, "buffer", None)
        raw = buf.read() if buf is not None else sys.stdin.read()
    except Exception:          # unreadable stdin stays unadjudicable
        return {}
    if not raw.strip():
        return {}
    if isinstance(raw, str):   # detached/replaced stdin without a buffer
        return _parse_payload_text(raw)
    text = None
    for enc in ("utf-8", locale.getpreferredencoding(False)):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    return _parse_payload_text(text)
```

- `utf-8` first: the Claude Code wire format is UTF-8; strict decode must win
  whenever the bytes are genuinely UTF-8.
- locale second: recovers the exact payload for any locale-defaulting caller
  on a non-UTF-8 host (the failing harness shape). The em-dash round-trips
  losslessly through `cp936`.
- `errors="replace"` last: neither charset fit; the JSON structure usually
  survives and the write gets adjudicated on its structural fields (statuses,
  ids, sign-offs are ASCII). Only a truly mangled payload degrades to `{}`.
- Reading bytes can never raise `UnicodeDecodeError`; the raise lived in the
  text layer, which is why the bug hid behind `except Exception`.

`_parse_payload_text` keeps the existing parse semantics
(`json.JSONDecodeError` → `{}`) plus one guard: a decoded non-dict JSON value
(list/scalar) degrades to `{}` instead of reaching `payload.get` and crashing
with `AttributeError` (rc=1 traceback class).

## D3. What is deliberately NOT changed

- The bare `except` on the **read** itself: an absent/closed stdin pipe is
  still "no payload" → allow (the hook must not block every non-writing tool
  call on machines with odd stdin plumbing).
- Allow-on-unparseable-JSON: documented #532 contract, unchanged.
- The four-carrier matcher, post-image reconstruction, shadow build, and all
  three adjudication legs: byte-identical.
- Fail-closed paths: unresolvable workspace + carrier shape still blocks;
  post_image None still blocks; checker crash still blocks.

## D4. `KUNGLAO_WG_DEBUG=1` trace channel

`_dbg(msg)` prints `wg-debug: <msg>` to stderr when the env var is `1`,
no-op otherwise (zero effect on the rc contract; stderr is already the block
channel, debug lines are additive). Trace points: payload decoded (+ charset
that succeeded), resolve result, carrier, post-image size, per-leg counts in
`adjudicate`, final decision + rc. This is the in-tree version of the
out-of-tree driver this investigation needed (evidence: without it, the
failure was blamed on the rule layer for days).

## D5. Test strategy (RED-first)

RED file `tests/test_write_guard_686.py`, harness = the 532 subprocess-stdin
shape (`[sys.executable, WRITE_GUARD]`, `input=payload`, PYTHONIOENCODING=utf-8,
PYTHONPATH=repo/hooks/scripts):

- 7 parametrized must-block cases, one per issue-listed failure, payloads
  copied verbatim from the existing suites (em-dashes included — they are the
  trigger, removing them would turn the test into an ASCII-only false pass).
- 2 allow guards (clean em-dash fact write → rc=0; non-carrier write → rc=0)
  to kill degenerate always-block fixes and pin the recovered allow path.
- Expected RED on dev: 7 failed / 2 passed. Expected GREEN after the fix: 9/9.
- Cross-check: `tests/test_write_guard_532.py` +
  `tests/test_write_guard_supersedes_528.py` must reach 23/23 — this also
  converts two false-greens (clean-content allow, chained-pending allow;
  both currently pass via the decode-crash path) into true greens.

## D6. Risks

- A payload that is valid UTF-8 AND valid GBK is impossible for the em-dash
  class (GBK lead bytes are invalid UTF-8 continuation bytes), so the chain
  order cannot mis-decode a genuine Claude Code payload.
- `locale.getpreferredencoding(False)` may be `utf-8` (UTF-8 mode / modern
  hosts) — the chain then degrades to utf-8-only + replace, the current
  intended behavior; no error path.
- Python ≥3.11 `locale.getpreferredencoding` is not deprecated for reads;
  no warning noise under `-W error` suites.
