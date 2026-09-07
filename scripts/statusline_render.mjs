#!/usr/bin/env node
// statusline_render.mjs — kunglao statusline v2 renderer (issue #142).
//
// The repo-side renderer: a PURE VIEW over the producer snapshot
// (<ws>/runs/.kunglao-statusline.json, written by scripts/statusline_snapshot.py).
// All kunglao data is producer-owned — this script reads the ONE snapshot
// JSON and nothing else on the kunglao side (zero spawn, zero raw-log reads;
// the external combined-statusline's direct rl-signals.jsonl read was the
// contract violation #142 removes, and its undefined `blocked` reference on
// the coarse path — a strict-mode ReferenceError that killed the whole
// statusline — is the crash class this renderer structurally cannot have:
// every field is read off the parsed snapshot with ?? fallbacks).
//
// Contract: read stdin JSON once, pass through to claude-hud verbatim (when
// present), then append the kunglao line to the LAST line (Claude Code
// renders only the last statusline line). Watchdog kept: snapshot mtime
// older than T_LIVE -> render frozen "down" frame, never trust a stale
// "healthy" frame. Freshness kept: heartbeat_touch refreshes the snapshot
// per tool use (#142), idle refreshes per tick.
//
// Line shape (owner-approved, issue #142):
//   ◈ analyzing ▂▄▆█ 42% H1.3b ●●● │ C-409 sign-algo probe ⚡CASE-GREEN
// Four-meaning palette ONLY (color IS data, no rainbow):
//   cyan = working (state)          green = learning/healthy (uptrend, H falling, solid dots)
//   amber = stall-suspect (H flat, retro-lag >= 8, DORMANT present)
//   red = broken (down, empty dot)
// Deleted as noise vs the external renderer: `CONVERGENCE HEALTH:` duplicate
// text, tick number, slope chip.

import { execFileSync } from 'node:child_process';
import { readFileSync, statSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

const T_LIVE_MS = 35 * 60 * 1000; // align with liveness_policy.HEARTBEAT_STALE_MINUTES
// Test seam: KUNGLAO_STATUSLINE_HUD='' disables the HUD passthrough so
// renderer tests are deterministic on machines that do have the plugin.
const HUD = process.env.KUNGLAO_STATUSLINE_HUD !== undefined
  ? process.env.KUNGLAO_STATUSLINE_HUD
  : `${process.env.HOME}/.claude/plugins/cache/claude-hud/claude-hud/0.1.0/dist/index.js`;

const FLASH_WINDOW_MS = 5000; // 5s fade window (render-clock side, kept)

// Four-meaning palette (ANSI SGR; color IS data — no decorative hues).
const PALETTE = {
  cyan: (s) => `\x1b[36m${s}\x1b[0m`,
  green: (s) => `\x1b[32m${s}\x1b[0m`,
  amber: (s) => `\x1b[33m${s}\x1b[0m`,
  red: (s) => `\x1b[31m${s}\x1b[0m`,
  dim: (s) => `\x1b[2m${s}\x1b[0m`,
};
// State hue system (kept): glyph + label ride the snapshot's state color.
const STATE_HUE_FALLBACK = { analyzing: 140, toss: 190, idle: 220, stall: 45, down: 0, flawless: 48 };
const GLYPHS = { analyzing: '◈', toss: '◇', idle: '○', stall: '◌', down: '✖', flawless: '◉' };
const STATE_LABELS = {
  analyzing: 'analyzing', toss: 'tossing', idle: 'idle',
  stall: 'stall', down: 'DOWN', flawless: 'flawless',
};
const SPARK_CHARS = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

function readStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function findSnapshot(startDir) {
  const start = resolve(startDir);
  // Probe DOWN one level first: session cwd is often the project root with
  // the workspace a child (known kunglao workspace dir names), then walk UP
  // from the dir (cwd may be inside the ws). Bounded, no globbing.
  const childDirs = ['analysis_workspace', 'malware-analysis-workspace'];
  for (const name of childDirs) {
    const p = join(start, name, 'runs', '.kunglao-statusline.json');
    if (existsSync(p)) return p;
  }
  let dir = start;
  for (let i = 0; i < 4; i++) {
    const p = join(dir, 'runs', '.kunglao-statusline.json');
    if (existsSync(p)) return p;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

// Sparkline of the last ~8 v_norm points (issue #142: momentum as shape).
// Normalized within the window — the shape is the signal, not the level.
function sparkline(vHist) {
  if (!Array.isArray(vHist)) return '';
  const vals = vHist.map((v) => Number(v)).filter((v) => Number.isFinite(v));
  if (vals.length === 0) return '';
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo;
  return vals
    .map((v) => SPARK_CHARS[Math.min(7, Math.floor((((v - lo) / (span || 1)) * 7.99)))])
    .join('');
}

// Uptrend within the sparkline window: last point strictly above the first
// is learning (green); flat/declining is stall-suspect (amber).
function isUptrend(vHist) {
  if (!Array.isArray(vHist)) return false;
  const vals = vHist.map((v) => Number(v)).filter((v) => Number.isFinite(v));
  if (vals.length < 2) return false;
  return vals[vals.length - 1] > vals[0];
}

// Health dots x3: oracle registered / retro lag < 8 / no DORMANT.
// ok -> green solid; suspect (retro lag, DORMANT) -> amber; broken (oracle
// unregistered) -> red; down -> all red empty (broken face).
function healthDots(health, down) {
  if (!health || typeof health !== 'object') return '';
  const specs = [
    { ok: health.oracle, suspect: false },
    { ok: health.retro, suspect: true },
    { ok: health.dormant, suspect: true },
  ];
  return specs
    .map(({ ok, suspect }) => {
      if (down) return PALETTE.red('○');
      if (ok) return PALETTE.green('●');
      return suspect ? PALETTE.amber('●') : PALETTE.red('●');
    })
    .join('');
}

// Current-task chip: `C-<id> <op short>` from the active worker; `idle ·
// last C-<id>` when parked. Producer truncates op to 24 chars; defensive
// re-trim here so the chip budget holds even on hand-built snapshots.
function taskChip(now) {
  if (!now || typeof now !== 'object') return '';
  const claim = typeof now.claim === 'string' ? now.claim.trim() : '';
  const op = typeof now.op === 'string' ? now.op.trim().slice(0, 24) : '';
  if (claim && op) return PALETTE.cyan(`${claim} ${op}`);
  if (claim) return PALETTE.cyan(`idle · last ${claim}`);
  return '';
}

function entropyBadge(snap) {
  if (typeof snap.h_bits !== 'number' || !Number.isFinite(snap.h_bits)) return '';
  const text = `H${snap.h_bits.toFixed(1)}b`;
  const trend = snap.h_trend;
  if (trend === 'falling') return PALETTE.green(text); // learning
  if (trend === 'rising') return PALETTE.red(text);    // luck/fake-progress alert
  return PALETTE.amber(text);                          // flat/unknown = suspect
}

function renderKunglao(snapPath, nowMs) {
  let snap;
  try {
    snap = JSON.parse(readFileSync(snapPath, 'utf8'));
  } catch {
    return '';
  }
  if (!snap || typeof snap !== 'object') return '';
  let mtime = 0;
  try {
    mtime = statSync(snapPath).mtimeMs;
  } catch {
    return '';
  }
  const down = nowMs - mtime > T_LIVE_MS;

  const state = down ? 'down' : (typeof snap.state === 'string' ? snap.state : 'idle');
  const stateLabel = STATE_LABELS[state] || 'idle';
  const glyph = GLYPHS[state] || '○';
  const hue = down ? 0 : (snap.color?.hue ?? STATE_HUE_FALLBACK[state] ?? 220);
  const stateColor = (s) =>
    `\x1b[38;5;${Math.max(1, Math.min(230, Math.round((hue / 360) * 230) + 16))}m${s}\x1b[0m`;

  // Value: sparkline of v_hist + percent (fine v_norm preferred, coarse PQ
  // fraction as fallback). The coarse path is a FIRST-CLASS render, not an
  // afterthought: `blocked` and friends are always declared via ?? fallbacks
  // (the external renderer's undefined `blocked` on exactly this path was
  // the line-137 strict-mode crash).
  const vHist = Array.isArray(snap.v_hist) ? snap.v_hist : [];
  const sparks = sparkline(vHist);
  const trendUp = isUptrend(vHist);
  const pq = snap.pq && typeof snap.pq === 'object' ? snap.pq : {};
  const answered = Number.isFinite(Number(pq.answered)) ? Number(pq.answered) : 0;
  const total = Number.isFinite(Number(pq.total)) ? Number(pq.total) : 0;
  const blocked = Number.isFinite(Number(pq.blocked)) ? Number(pq.blocked) : 0; // always declared
  let pct = null;
  if (Number.isFinite(Number(snap.v_norm)) && Number(snap.v_norm) > 0) {
    pct = Number(snap.v_norm);
  } else if (total > 0) {
    pct = answered / total;
  }
  const valueColor = down ? PALETTE.red : (trendUp ? PALETTE.green : PALETTE.amber);
  let valueSeg = '';
  if (pct !== null) {
    const bar = '█'.repeat(Math.round(pct * 10)) + '░'.repeat(10 - Math.round(pct * 10));
    const barText = sparks ? `${sparks} ${(pct * 100).toFixed(0)}%` : `${bar} ${(pct * 100).toFixed(0)}%`;
    valueSeg = valueColor(barText);
  } else if (total > 0) {
    valueSeg = valueColor(`PQ ${answered}/${total}` + (blocked ? ` (blocked ${blocked})` : ''));
  }

  const badge = entropyBadge(snap);
  const dots = healthDots(snap.health, down);
  const chip = taskChip(snap.now);

  // Flash (5s window, kept): producer-detected triggers ship {seq, ts, text}.
  let flash = '';
  if (snap.flash?.text && snap.flash?.ts) {
    try {
      const t = Date.parse(snap.flash.ts);
      if (Number.isFinite(t) && nowMs - t < FLASH_WINDOW_MS) {
        flash = ` ${PALETTE.amber(`⚡${snap.flash.text}`)}`;
      }
    } catch { /* ignore */ }
  }

  const parts = [stateColor(`${glyph} ${stateLabel}`)];
  if (valueSeg) parts.push(valueSeg);
  if (badge) parts.push(badge);
  if (dots) parts.push(dots);
  if (chip) parts.push(PALETTE.dim('│'), chip);
  if (flash) parts.push(flash.trim());
  return parts.join(' ');
}

function main() {
  const stdinText = readStdin();
  let hudOut = '';
  if (HUD) {
    try {
      if (existsSync(HUD)) {
        hudOut = execFileSync('node', [HUD], { input: stdinText, encoding: 'utf8', timeout: 8000 });
      }
    } catch {
      hudOut = '';
    }
  }

  const cwd = (() => {
    try {
      const j = JSON.parse(stdinText);
      return j?.workspace?.current_dir || process.cwd();
    } catch {
      return process.cwd();
    }
  })();

  const snapPath = findSnapshot(cwd);
  const kunglaoSeg = snapPath ? renderKunglao(snapPath, Date.now()) : '';

  const lines = hudOut.replace(/\n+$/, '').split('\n').filter((l) => l !== '');
  if (!kunglaoSeg) {
    process.stdout.write(hudOut);
    return;
  }
  // kunglao metrics on their OWN last line (Claude Code renders only the
  // last statusline line); HUD lines stay above untouched.
  lines.push(kunglaoSeg);
  process.stdout.write(lines.join('\n') + '\n');
}

main();
