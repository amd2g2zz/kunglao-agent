## Design (self-reviewed against: #462 kernel actuation change — envelope synthesis is a kernel face; #476 audit fixes — llm_faces wave cage; both read)
Decisions:
1. The guidance block is added to the ONE envelope mint site (_run_dispatch_act's prompt_file) — single point, all three faces inherit.
2. STATUS protocol is guidance-only; the BLOCKED parser's regex already handles prose, so no parser change (keeps the diff minimal; the parser consumes STATUS: BLOCKED via the same \bblocked\b match).
3. Timeout: module constant becomes a function of env read at import; no per-act reads (deterministic within a run).
Edge considerations: envelope size growth is ~3 lines; no test currently pins envelope bytes except the two registration tests — updated accordingly.
