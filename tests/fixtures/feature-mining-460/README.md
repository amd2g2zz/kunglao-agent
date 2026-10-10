# feature-mining-460 fixtures

Sanitized, machine-independent copies (shapes byte-contract-accurate to
the 2026-09-29/30 e2e-run-v016 artifacts; no absolute paths, no live
prompt bodies, no secrets). `root/` is a mining root:

- `runs/e2e/e2e-fix-211504-a` — landed + timeout + unpaired mix; the
  C-004 dispatch prompt declares the registered #432 token
  `static-decompile` (envelope-wins path); `ws/e2e-ws-a` carries a
  rollout ledger settlement for `task/C-005` (settled-dispatched-claim
  join). #460 intake-battery era: `ws/e2e-ws-a` additionally carries
  the battery artifacts (`evidence/die.json` + `evidence/apkid.json` +
  the `evidence/intake-battery.json` ledger over the staged entry
  `target/beacon.apk`, and the promise prescan states flipped to
  `available` via the usable-evidence chain) — synthesized demo data
  in the exact battery byte-shapes; the golden row proves battery
  outputs are minable with zero miner changes.
- `runs/e2e/e2e-fix-221504-b` — timeout / blocked / rc-null triple;
  `ws/e2e-ws-b` carries die.json + apkid.json + difficulty.json
  (probe-present path).
- `runs/e2e/e2e-fix-231630-c` — degraded run: ws pointer dangles
  (`ws/e2e-ws-gone`), task_dir present.

`golden/feature-table.jsonl` is the miner's output over `root/`,
pinned by the determinism test. Live mining targets process data
(kunglao-wt roots) and is never committed.
