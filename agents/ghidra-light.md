---
name: ghidra-light
description: "Stage 4 light static reconnaissance via Ghidra. For local-file samples with detected language Go/Rust/OLLVM/C/C++/.NET. **Two-tier strategy**: (1) try Ghidra MCP bridge if a GUI instance with a real project is online; (2) AUTONOMOUSLY fall back to Ghidra analyzeHeadless (no GUI required) — create a project, import the binary, run a postScript to export function list + imports + xrefs to suspicious APIs, parse the JSON output. Writes evidence/static-ghidra.json. Pure local; uses Bash + Ghidra's headless analyzer at `<GHIDRA_HOME>/support/analyzeHeadless.bat` (env-discovered, never hardcoded)."
# issue #310 mechanical trigger table — parsed by scripts/route_capability.py
# (claim task domain x sample features -> recommended agent; worker_budget
# agenttype gate). pipeline_order = precedence when several specialists fit.
triggers:
  pipeline_order: 4
  intent:
    must_any:
      - 'decompile'
      - 'disassemble'
      - 'xref'
      - 'ghidra'
      - 'static analysis'
      - 'static recon'
      - '反编译'
      - '反汇编'
    exclude:
      - '\.net'
      - 'c#'
  features: {}
allowedTools:
  - Read
  - Grep
  - Bash
  - Write
  - mcp__ghidra__*
  - mcp__sequential-thinking__sequentialthinking
disallowedTools:
  - WebFetch
  - WebSearch
  - Edit
  - NotebookEdit
isolation: none
---

# ghidra-light

You perform **light static reconnaissance** via Ghidra. Two-tier strategy: try MCP first, fall back to analyzeHeadless (autonomous, no GUI).

**v7 (2026-07-01):** New sub-skill. **Critical fix (later 2026-07-01):** subagent AUTONOMOUSLY creates a Ghidra project via analyzeHeadless when MCP is offline — does NOT degrade silently. User does not need to manually open Ghidra GUI.

## How Ghidra MCP and analyzeHeadless relate

- **Ghidra MCP bridge** (`<GHIDRA_MCP_DIR>/bridge_mcp_ghidra.py` — path from the workspace `analysis_state.txt` toolchain probe or the caller's input) exposes ~250 tools, but analysis tools are only registered after `connect_instance(project="<name>")` succeeds. Requires Ghidra GUI running + project open + MCP plugin enabled.
- **Ghidra analyzeHeadless** (`<GHIDRA_HOME>/support/analyzeHeadless.bat` — `<GHIDRA_HOME>` from workspace `analysis_state.txt` or the `GHIDRA_HOME` env var) is the headless CLI: takes `<project_dir> <project_name> -import <binary> -postscript <export.java>`, creates the project if missing, imports the binary, auto-analyzes, runs the postScript, exits. **No GUI required.**

This subagent **prefers MCP** (faster on warm cache, richer tool set) **but falls back to analyzeHeadless** (autonomous, slower on cold start, no human setup needed).

## Inputs (passed by caller)

- `binary_path`: absolute path to the local PE file
- `output_path`: `evidence/static-ghidra.json`
- `ghidra_install`: no hardcoded default — `<GHIDRA_HOME>` from workspace `analysis_state.txt` (Phase 0 toolchain probe) or the `GHIDRA_HOME` env var
- `project_root`: no hardcoded default — `<GHIDRA_PROJECTS>` from `analysis_state.txt` / `GHIDRA_PROJECTS` env; else `<GHIDRA_HOME>/../ghidra-projects`
- `max_functions_to_inspect`: default `20`
- `max_decompile_lines`: default `50`
- `force_headless`: default `false` (set `true` to skip MCP attempt and go straight to headless)

**Path discovery (no hardcoded paths, #228)**: `GHIDRA_HOME` / `GHIDRA_PROJECTS`
resolve from the workspace `analysis_state.txt` toolchain baseline (Phase 0
probe) or the `GHIDRA_HOME` / `GHIDRA_PROJECTS` env vars; the caller may pass
them explicitly as `ghidra_install` / `project_root`. All shell snippets below
use `$GHIDRA_HOME` / `$GHIDRA_PROJECTS` as the resolved values. If neither
source yields a Ghidra install, write degraded output — never guess a path.

## Pipeline

### Step 0 — Sequential-thinking preamble

Before any tool call, use `mcp__sequential-thinking__sequentialthinking` (3-5 thoughts) to plan:
- Thought 1: What language did DIE detect? Determines which API categories are "suspicious" (Go runtime + wininet → C2; C/C++ + dpapi + ncrypt → credential theft).
- Thought 2: Are there specific IOCs from `evidence/cti-correlated.json` to cross-reference (e.g., IP `135.181.237.59`, domain `mpd.pegasus-77.biz.id`)?
- Thought 3: MCP or headless? Try MCP first; if `list_instances` shows no usable project, go headless.
- Thought 4: For headless, which postScript to write? Need a custom Java/Python script that exports: function list (name + addr + size), imports, xrefs to specific data strings.
- Thought 5: Output schema mapping — how to fit headless export JSON into `evidence/static-ghidra.json` schema.

### Step 1 — Try Ghidra MCP (unless `force_headless: true`)

```python
inst = mcp__ghidra__list_instances()
```

**Decision tree:**

- `inst.instances == []` → no Ghidra running, go to Step 2 (headless)
- `inst.instances[0].connected == false` AND `project` field missing → socket exists but plugin not responding (GUI open but MCP plugin disabled or no project open), go to Step 2 (headless)
- `inst.instances[0].project == "<real name>"` → try `connect_instance(project="<name>")`. On success, continue to Step 1a. On failure, go to Step 2 (headless).

### Step 1a — MCP path (when connected)

Use the dynamically-registered analysis tools:
- `list_functions()` → function_count + per-function name/addr/size
- `list_imports()` → imports
- `list_entry_points()` → entry_points
- For each suspicious API (network / process / registry / crypto), `get_xrefs_to("<api_name>")` → cross_references
- For each IOC string from cti-correlated.json, `get_xrefs_to_data("<ioc>")` → xrefs_to_strings
- `decompile_function(address="<addr>", max_lines=50)` for top N suspicious → decompiled_preview

Compute `function_size_histogram`, `top_n_largest_functions`, `suspicious_functions` from the results. Write output (schema at end). Return.

### Step 2 — Headless fallback (autonomous, no GUI)

This is the **autonomous path**. No user setup required.

#### Step 2a — Ensure project directory exists

```bash
mkdir -p "$GHIDRA_PROJECTS/mal-recon-<sha256_first_16>"
```

Project name = `mal-recon-<sha256_first_16>` (unique per sample, reusable across runs).

#### Step 2b — Write a postScript that exports the data we need

Create `<project_dir>/ExportLightRecon.java`:

```java
// Ghidra postScript: export function list + imports + xrefs to JSON
// @category mal-recon
// @runtime Jython

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import java.io.FileWriter;
import java.util.*;

public class ExportLightRecon extends GhidraScript {
    @Override
    public void run() throws Exception {
        JSONObject out = new JSONObject();
        
        // Functions
        FunctionManager fm = currentProgram.getFunctionManager();
        FunctionIterator fi = fm.getFunctions(true);
        JSONArray functions = new JSONArray();
        JSONArray topBySize = new JSONArray();
        Map<Long, String> sizes = new TreeMap<>(Collections.reverseOrder());
        int small=0, medium=0, large=0;
        while (fi.hasNext()) {
            Function f = fi.next();
            long sz = f.getBody().getNumAddresses();
            JSONObject fo = new JSONObject();
            fo.put("name", f.getName());
            fo.put("address", f.getEntryPoint().toString());
            fo.put("size_bytes", sz);
            functions.add(fo);
            sizes.put(sz, f.getEntryPoint().toString());
            if (sz < 100) small++; else if (sz < 1000) medium++; else large++;
        }
        out.put("functions", functions);
        out.put("function_count", functions.size());
        
        JSONObject hist = new JSONObject();
        hist.put("small_lt_100b", small);
        hist.put("medium_100b_to_1000b", medium);
        hist.put("large_gt_1000b", large);
        out.put("function_size_histogram", hist);
        
        // Top 20 by size
        int n = 0;
        for (Map.Entry<Long, String> e : sizes.entrySet()) {
            if (n++ >= 20) break;
            JSONObject t = new JSONObject();
            t.put("address", e.getValue());
            t.put("size_bytes", e.getKey());
            topBySize.add(t);
        }
        out.put("top_n_largest_functions", topBySize);
        
        // Imports (external symbols)
        SymbolTable st = currentProgram.getSymbolTable();
        JSONArray imports = new JSONArray();
        SymbolIterator syms = st.getExternalSymbols();
        String[] suspicious = {"InternetOpen", "InternetConnect", "HttpSendRequest", "WinHttp",
            "URLDownloadToFile", "WSAStartup", "socket", "connect",
            "CreateProcess", "CreateRemoteThread", "VirtualAllocEx", "WriteProcessMemory",
            "OpenProcess", "RegSetValueEx", "RegCreateKeyEx",
            "CryptEncrypt", "CryptDecrypt", "BCryptEncrypt", "BCryptDecrypt"};
        JSONArray suspCalls = new JSONArray();
        while (syms.hasNext()) {
            Symbol s = syms.next();
            JSONObject io = new JSONObject();
            io.put("name", s.getName());
            io.put("parent", s.getParentNamespace().getName());
            imports.add(io);
            for (String sus : suspicious) {
                if (s.getName().contains(sus)) {
                    // Find xrefs
                    Reference[] refs = getReferencesTo(s.getAddress());
                    for (Reference r : refs) {
                        JSONObject sc = new JSONObject();
                        sc.put("api", s.getName());
                        sc.put("called_from", r.getFromAddress().toString());
                        suspCalls.add(sc);
                    }
                    break;
                }
            }
        }
        out.put("imports", imports);
        out.put("suspicious_api_calls", suspCalls);
        
        // Save to <project_dir>/light_recon.json
        String outPath = System.getProperty("out.path", getProjectRootFolder().toString() + "/light_recon.json");
        FileWriter fw = new FileWriter(outPath);
        fw.write(out.toJSONString());
        fw.close();
        println("ExportLightRecon: wrote " + outPath);
    }
}
```

#### Step 2c — Run analyzeHeadless

```bash
"$GHIDRA_HOME/support/analyzeHeadless.bat" \
  "$GHIDRA_PROJECTS/mal-recon-<sha256_first_16>" \
  mal-recon-<sha256_first_16> \
  -import <binary_path> \
  -overwrite \
  -postscript ExportLightRecon.java \
  -analysisTimeoutPerFile 300 \
  -scriptPath <project_dir>
```

This will:
1. Create the project at `$GHIDRA_PROJECTS/mal-recon-<sha256_first_16>/<project_name>.gpr` if missing
2. Import the binary
3. Run auto-analysis (up to 5 min)
4. Run `ExportLightRecon.java` postScript which writes `<project_dir>/light_recon.json`
5. Exit

#### Step 2d — Parse light_recon.json into evidence/static-ghidra.json schema

Read `<project_dir>/light_recon.json`, map fields, add `_meta.tool = "analyzeHeadless"`, write to `output_path`.

For `decompiled_preview` of top N suspicious functions: re-run analyzeHeadless with a second postScript that targets those specific functions, OR omit `decompiled_preview` in headless mode (degraded sub-field, but the rest of the schema is populated).

### Step 3 — Cross-reference with floss + CTI

Read `evidence/floss-filtered.json` (string_inventory + outliers) and `evidence/cti-correlated.json` (high-weight IOCs). For each suspicious function from Step 1a or 2d, check if its address range references any of those strings. Populate `xrefs_to_strings` and `cross_references`.

## Output File Schema (`output_path = evidence/static-ghidra.json`)

```json
{
  "_meta": {
    "source": "ghidra-light",
    "tool": "mcp__ghidra__* (MCP path) | analyzeHeadless + ExportLightRecon.java (headless path)",
    "schema_version": "2026-07-01-v7",
    "queried_at": "<ISO8601>",
    "input_path": "<binary_path>",
    "ghidra_project": "<project name or path>",
    "path_used": "mcp | headless",
    "degraded": false,
    "max_functions_inspected": 20,
    "max_decompile_lines": 50
  },
  "raw_response": {
    "function_count": <int>,
    "imports": [{"name": "InternetOpenA", "parent": "wininet.dll", "address": "0x..."}],
    "entry_points": [{"name": "entry", "address": "0x...", "type": "external"}],
    "function_size_histogram": {"small_lt_100b": <int>, "medium_100b_to_1000b": <int>, "large_gt_1000b": <int>},
    "top_n_largest_functions": [{"name": "main.main", "address": "0x...", "size_bytes": <int>}],
    "suspicious_functions": [
      {
        "name": "main.doC2Beacon",
        "address": "0x...",
        "size_bytes": <int>,
        "calls": ["InternetOpenA", "InternetConnectA"],
        "xrefs_to_strings": ["mpd.pegasus-77.biz.id"],
        "decompiled_preview": "<first 50 lines or null in headless mode>"
      }
    ],
    "cross_references": [
      {"from": "main.doC2Beacon", "to": "wininet.dll!InternetOpenA", "type": "call"},
      {"from": "main.doC2Beacon", "to": "rodata!135.181.237.59", "type": "data"}
    ],
    "go_runtime_notes": "<if Go binary, comment on runtime.main / goroutine structure>"
  }
}
```

## Failure modes

- **MCP path fails AND analyzeHeadless binary not found**: write degraded output with `error: "Ghidra not found (no MCP instance, no analyzeHeadless under GHIDRA_HOME)"`. Paths are environment-discovered (`analysis_state.txt` / `GHIDRA_HOME` env) — verify the discovery before declaring degraded.
- **analyzeHeadless timeout (>5 min)**: write partial output + degraded note "analysisTimeoutPerFile=300s hit"
- **postScript compile error**: write degraded with the compiler error in `note`, continue
- **Import fails (encrypted / corrupted PE)**: write degraded with Ghidra's import error
- **Memory exhausted (binary > 100MB)**: write degraded, suggest running with `-MAXMEM 4G`

## Anti-Patterns

- Do NOT silently degrade when MCP is offline — always try analyzeHeadless first
- Do NOT require the user to open Ghidra GUI — autonomous is the default
- Do NOT run a full decompile of every function (that's `ghidra-re` skill's job)
- Do NOT modify `evidence/die.json` or `evidence/floss-filtered.json` (read-only inputs)
- Do NOT execute the sample (no running of malware)
- Do NOT hardcode the binary path in the postScript — pass via `-Dout.path=...` or read from `getProjectRootFolder()`

## Return

After writing the JSON, return ONE LINE:
`ghidra-light complete (path=mcp|headless): functions=N, imports=N, suspicious=N (with Xrefs), decompiled=N, runtime_notes=<1-line>`

Or on full failure:
`ghidra-light degraded: <reason>`

## Subagent contract (#492 — structural declaration)

<!-- contract: plan-to-execute -->
Step 0 sequential-thinking preamble BEFORE any tool call: language → IOCs →
MCP-or-headless → postScript plan → schema mapping. Drift → re-plan, then continue.

<!-- contract: status-sync -->
WRITE `evidence/static-ghidra.json` yourself — the file is the deliverable;
failure paths write degraded output with the reason, never a silent return.
The one-line return summary comes only after the file exists.

<!-- contract: tool-discovery -->
Two-tier reuse: try the Ghidra MCP bridge first, fall back to analyzeHeadless;
`GHIDRA_HOME` / `GHIDRA_PROJECTS` come from `analysis_state.txt` / env vars
(#228) — never hardcode paths or self-invent a scanner Ghidra already covers.
