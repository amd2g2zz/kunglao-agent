# Go Binary Reverse Engineering Guide

> Go-compiled binaries pose unique challenges: static linking makes them huge, function counts reach tens of thousands, the string format is unusual, and stripped symbols are hard to recover.
> This document covers the toolchain, recovery techniques, and practical workflows.

---

## Identifying Go binaries

Quick checks for whether a binary is Go-compiled:

```bash
# String traits
strings binary | grep -E "runtime\.|go\.buildid|GOROOT"

# rabin2 reconnaissance
rabin2 -z binary | grep -i "runtime"

# Abnormally large file size (statically linked runtime)
# Typical Hello World: C ~20KB, Go ~2MB
```

Common traits:
- Large numbers of functions with the `runtime.` prefix
- Presence of a `go.buildid` section
- Presence of `GOROOT`/`GOPATH` path strings
- 5000-50000+ functions (the whole runtime and standard library included)

---

## Core toolchain

### Symbol recovery

| Tool | Purpose | Link |
|------|------|------|
| **GoReSym** | By Mandiant; parses Go symbol info (pclntab/moduledata) | https://github.com/mandiant/GoReSym |
| **GoResolver** | By Volexity; auto-deobfuscates Garble binaries via CFG similarity | https://github.com/volexity/GoResolver |
| **redress** | Analyzes stripped Go binaries; recovers types/interfaces/package structure | https://github.com/goretk/redress |
| **GoStringUngarbler** | Restores strings obfuscated by Garble | https://github.com/mandiant/GoStringUngarbler |

### IDA plugins

| Tool | Purpose | Link |
|------|------|------|
| **go_parser** | IDA plugin that parses moduledata/pclntab/type info | https://github.com/0xjiayu/go_parser |
| **IDAGolangHelper** | IDA script collection that parses Go type info | https://github.com/sibears/IDAGolangHelper |
| **AlphaGolang** | SentinelLabs IDAPython script collection | https://github.com/SentineLabs/AlphaGolang |
| **IDA 9.2+ native support** | Hex-Rays official Go decompiler improvements | https://hex-rays.com/blog/stop-guessing-and-start-going |

### Ghidra plugins

| Tool | Purpose | Link |
|------|------|------|
| **Ghidra + GoReSym output** | Export symbols with GoReSym, import into Ghidra | Used together |
| **golang_loader_assist** | Ghidra Go loading assistance | Community script |

### Standalone analysis tools

| Tool | Purpose | Link |
|------|------|------|
| **gore** | Go RE library (the engine under redress) | https://github.com/goretk/gore |
| **garble** | The Go obfuscator (know it to counter it) | https://github.com/burrowers/garble |

---

## Key Go binary structures

### pclntab (PC Line Table)

The most important structure in a Go binary. It contains:
- The mapping of all function names to addresses
- Source file paths
- Line-number information
- Stack frame sizes

Even with symbols stripped, pclntab usually survives (the Go runtime depends on it).

```text
How to locate it:
1. Search for magic bytes: 0xFFFFFFF0 (Go 1.16+) or 0xFFFFFFFB (Go 1.18+)
2. Auto-locate with GoReSym
3. Auto-parse with the go_parser IDA plugin
```

### moduledata

Contains:
- pclntab pointer
- Type information tables
- itab (interface table)
- Global variable info

### String format

Go strings are not C-style null-terminated; they are (pointer, length) structs:

```text
C string:   "hello\0"
Go string:  struct { ptr *byte; len int } -> ptr points at "hello" (no \0)
```

As a result, default string detection in IDA/Ghidra misses large numbers of Go strings.

**Solutions:**
- Use `go_parser` to auto-identify Go strings
- Export the string list with GoReSym
- Manually: find `runtime.stringtable` or locate them via cross-references

---

## Practical workflows

### Scenario 1: Non-stripped Go binary

```text
1. GoReSym -t -d -p binary > symbols.json
   -> export all function names, types, source file paths
2. Load into IDA/Ghidra
3. Import the GoReSym symbol information
4. Filter out runtime.* and standard-library functions; focus on user code
5. Start analysis from main.main
```

### Scenario 2: Stripped Go binary

```text
1. GoReSym -t -d -p binary > symbols.json
   -> even when stripped, pclntab usually survives
2. If GoReSym fails -> use redress
   redress -src binary    # recover source file paths
   redress -pkg binary    # recover package structure
   redress -type binary   # recover type information
3. Load into IDA + the go_parser plugin
4. Run go_parser for automatic recovery
5. Start from the recovered main.main
```

### Scenario 3: Garble-obfuscated Go binary

```text
Garble will:
- Randomize function names (main.main -> main.a3f2b1c)
- Encrypt strings
- Remove file path information
- Obfuscate package names

Countermeasures:
1. GoResolver (CFG signature matching)
   -> recover standard-library function names via control-flow-graph similarity
2. GoStringUngarbler (string decryption)
   -> auto-detect Garble's string encryption pattern and decrypt
3. Dynamic analysis (Frida/dlv)
   -> hook runtime functions to observe actual behavior
4. Comparative analysis
   -> compile a Hello World with the same Go version and binary-diff the runtime parts
```

### Scenario 4: Mixed CGo builds

```text
1. Identify the CGo boundary (_cgo_* functions)
2. Recover the Go part with go_parser
3. Analyze the C part with regular IDA
4. Watch bridge functions like _cgo_topofstack and crosscall2
```

---

## Common command cheat sheet

```bash
# GoReSym: export symbols
GoReSym -t -d -p binary > symbols.json
GoReSym -t -d -p binary -o ida_script.py  # generate an IDA script

# redress: analyze stripped binaries
redress -src binary          # source file paths
redress -pkg binary          # package structure
redress -type binary         # type information
redress -interface binary    # interface information
redress -filepath binary     # full file paths

# GoResolver: deobfuscate Garble
GoResolver -binary binary -output resolved.json

# GoStringUngarbler: decrypt Garble strings
GoStringUngarbler -i binary -o deobfuscated_binary

# Quickly determine the Go version
strings binary | grep "go1\."
GoReSym -p binary | grep "Version"
```

---

## Go analysis flow in IDA

```text
1. Load the binary (choose the correct architecture)
2. Wait for auto-analysis to finish
3. Run the go_parser plugin:
   - File -> Script File -> go_parser.py
   - or Edit -> Plugins -> Go Parser
4. The plugin automatically:
   - Parses pclntab
   - Recovers function names
   - Marks Go strings
   - Parses type information
5. Filter the view:
   - Hide runtime.* functions
   - Focus on main.* and third-party packages
6. Start reversing from main.main
```

---

## Common pitfalls

| Pitfall | Notes | Solution |
|------|------|------|
| Too many functions to scan | Go static linking yields 5000-50000 functions | Filter by package; look only at main.* and business packages |
| Incomplete string detection | Go strings are not null-terminated | Recover with go_parser or GoReSym |
| Hard-to-read decompilation | defer/goroutine/interface bloat the pseudocode | IDA 9.2+ is improved; assist with dynamic analysis |
| Garble obfuscation | Function names/strings fully randomized | GoResolver + GoStringUngarbler |
| Version differences | pclntab formats differ across Go versions | GoReSym supports Go 1.2-1.23+ |
| CGo boundary | Mixed Go and C code | Use _cgo_* functions as the dividing line |

---

## Working with other skills

| Need | Use |
|------|--------|
| Deep Go analysis in IDA | `ida-reverse/` + the go_parser plugin |
| Ghidra analysis (free) | Ghidra + GoReSym symbol import |
| Fast reconnaissance | `radare2/` — `rabin2 -z` for strings |
| Dynamic hooking | Frida (hook runtime functions) or dlv (native Go debugger) |
| Cross-version comparison | `binary-diff/` — migrate symbols from an old version to a new one |
| Garble deobfuscation | GoResolver + GoStringUngarbler |
