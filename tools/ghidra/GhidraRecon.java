// GhidraRecon.java — focused static reconnaissance postScript (issue #293).
//
// Merges the Windows host-recon and Go-optimized light-recon postScripts into
// one parameterized tool. No sample-specific hashes / markers are embedded:
// search terms, expected exports and sample SHA metadata are passed in.
//
// Args (--key=value, unified #293 style):
//   --out=<abs path>             JSON output (default: <project>/ghidra_recon.json)
//   --search-terms=a,b,...       case-insensitive strings of interest
//   --expected-exports=A,B,...   export names to focus (default: all exports)
//   --focus=a,b,...              substrings marking a string as "focus" (default: search-terms)
//   --decompile=true|false       decompile focus functions (default true)
//   --max-decompile-bytes=<n>    skip decompile for larger functions (default 8192)
//   --mode=auto|go|native        Go runtime/garble detection (default auto)
//   --sha256=<hex> --sha1=<hex>  sample metadata embedded in meta (optional)
//
// Output: UTF-8 JSON with schema/program/image_base, self-contained JSON writer
// (no org.json.simple dependency).

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.program.model.symbol.SymbolType;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

public class GhidraRecon extends GhidraJsonScript {

    private static final int MAX_RAW_STRING_BYTES = 16384;
    private static final int DECOMPILE_TIMEOUT_SECONDS = 60;
    private static final String DEFAULT_SCHEMA = "ghidra_recon.v1";

    // Suspicious API keywords (case-insensitive), from the Go light-recon source.
    private static final String[] SUSPICIOUS_API = {
        "BCrypt", "Crypt", "NCrypt", "DPAPI",
        "WinHttp", "URLDownload", "InternetOpen", "InternetConnect",
        "HttpSendRequest", "HttpOpenRequest", "InternetReadFile",
        "WSAStartup", "WSASocket", "socket", "connect", "send", "recv",
        "getaddrinfo", "gethostbyname",
        "CreateProcess", "CreateRemoteThread", "VirtualAlloc", "VirtualAllocEx",
        "WriteProcessMemory", "NtWriteVirtualMemory", "NtCreateThreadEx",
        "OpenProcess", "ResumeThread", "QueueUserAPC", "SetThreadContext",
        "ZwAllocateVirtualMemory", "RtlCreateUserThread",
        "RegSetValueEx", "RegCreateKeyEx", "RegOpenKeyEx", "RegQueryValueEx",
        "RegDeleteKey", "RegCloseKey",
        "FindFirstFile", "FindNextFile", "CreateFile", "ReadFile", "WriteFile",
        "CopyFile", "MoveFile", "DeleteFile", "GetFileAttributes",
        "IsDebuggerPresent", "CheckRemoteDebuggerPresent", "NtQueryInformationProcess",
        "GetTickCount", "QueryPerformanceCounter", "SetErrorMode",
        "sqlite3", "NSS", "PK11", "SEC",
        "OpenClipboard", "GetClipboardData",
        "BitBlt", "CreateCompatibleDC", "GetDC",
        "LoadLibrary", "GetProcAddress",
        "winmm", "mciSendString"
    };

    // Go runtime package prefixes to filter out.
    private static final Set<String> RUNTIME_PFX = Collections.unmodifiableSet(
        new LinkedHashSet<>(Arrays.asList(
            "runtime", "internal", "vendor", "sync", "reflect", "unicode",
            "math", "encoding", "fmt", "strings", "strconv", "syscall",
            "time", "os", "io", "bytes", "sort", "path", "context",
            "errors", "hash", "bufio", "regexp", "compress", "container",
            "crypto/internal", "debug", "flag", "html", "image", "index",
            "log", "mime", "net", "plugin", "text", "unsafe", "go",
            "type", "itab", "gc", "mem", "cpu"
        ))
    );

    private static final Pattern GARBLE_PATTERN = Pattern.compile(
        "^main\\.[a-zA-Z0-9_]{5,20}$"
    );

    private static final class StringRecord {
        final String value;
        final Address address;
        final String type;
        final int byteLength;
        final List<String> matchedTerms;

        StringRecord(String value, Address address, String type, int byteLength,
                List<String> matchedTerms) {
            this.value = value;
            this.address = address;
            this.type = type;
            this.byteLength = byteLength;
            this.matchedTerms = matchedTerms;
        }
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = getArg(args, "out",
            System.getProperty("java.io.tmpdir") + "/ghidra_recon.json");
        List<String> searchTerms = parseCsv(getArg(args, "search-terms",
            "http,https,socket,beacon,cmd,powershell,password,admin"));
        List<String> expectedExports = parseCsv(getArg(args, "expected-exports", ""));
        List<String> focusTerms = parseCsv(getArg(args, "focus", ""));
        if (focusTerms.isEmpty()) {
            focusTerms = searchTerms;
        }
        boolean decompile = getBoolArg(args, "decompile", true);
        long maxDecompileBytes = Long.decode(getArg(args, "max-decompile-bytes", "8192"));
        String mode = getArg(args, "mode", "auto").toLowerCase(Locale.ROOT);
        String sha256 = getArg(args, "sha256", "");
        String sha1 = getArg(args, "sha1", "");

        List<Map<String, Object>> imports = collectImports();
        List<Map<String, Object>> exports = collectExports(expectedExports);
        List<Map<String, Object>> functions = collectFunctions(expectedExports);
        List<StringRecord> strings = collectStringsOfInterest(searchTerms);
        List<Map<String, Object>> suspiciousCalls = collectSuspiciousApiCalls();
        Map<Function, List<StringRecord>> references = collectReferencingFunctions(strings);
        List<Function> focusFunctions = selectFocusFunctions(exports, references, focusTerms);
        List<Map<String, Object>> decompiled = decompile
            ? decompileFocusFunctions(focusFunctions, references, maxDecompileBytes)
            : Collections.emptyList();
        List<Map<String, Object>> goStats = computeGoStats(functions, mode);
        List<String> findings = buildFindings(searchTerms, imports, exports, functions,
            strings, suspiciousCalls, focusFunctions, decompiled);

        Map<String, Object> root = new LinkedHashMap<>();
        Map<String, Object> m = meta(DEFAULT_SCHEMA, "GhidraRecon.java");
        if (!sha256.isEmpty()) {
            m.put("sha256", sha256);
        }
        if (!sha1.isEmpty()) {
            m.put("sha1", sha1);
        }
        root.put("meta", m);
        root.put("imports", imports);
        root.put("exports", exports);
        root.put("functions", functions);
        root.put("strings_of_interest", toStringMaps(strings));
        root.put("suspicious_api_calls", suspiciousCalls);
        root.put("focus_functions", decompile
            ? decompiled : functionNameMaps(focusFunctions));
        root.put("go", goStats);
        root.put("findings", findings);

        writeJson(outPath, root);
        println("GhidraRecon: wrote " + outPath);
    }

    // ---- arg helpers ----

    private List<String> parseCsv(String raw) {
        List<String> result = new ArrayList<>();
        if (raw == null || raw.trim().isEmpty()) {
            return result;
        }
        for (String part : raw.split(",")) {
            String trimmed = part.trim();
            if (!trimmed.isEmpty()) {
                result.add(trimmed);
            }
        }
        return result;
    }

    // ---- imports / exports / functions ----

    private List<Map<String, Object>> collectImports() {
        SymbolTable symbolTable = currentProgram.getSymbolTable();
        SymbolIterator iterator = symbolTable.getExternalSymbols();
        Map<String, Map<String, Object>> unique = new LinkedHashMap<>();
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Symbol symbol = iterator.next();
            if (symbol.getSymbolType() != SymbolType.FUNCTION) {
                continue;
            }
            String dll = symbol.getParentNamespace() == null
                ? "<unknown>" : symbol.getParentNamespace().getName();
            String function = symbol.getName();
            String key = dll.toLowerCase(Locale.ROOT) + " " + function;
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("dll", dll);
            item.put("function", function);
            unique.putIfAbsent(key, item);
        }
        List<Map<String, Object>> result = new ArrayList<>(unique.values());
        result.sort(Comparator.comparing(
            item -> String.valueOf(item.get("dll")) + "!" + String.valueOf(item.get("function")),
            String.CASE_INSENSITIVE_ORDER));
        return result;
    }

    private List<Map<String, Object>> collectExports(List<String> expectedExports) {
        SymbolIterator iterator = currentProgram.getSymbolTable().getAllSymbols(false);
        Map<String, Map<String, Object>> candidates = new LinkedHashMap<>();
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Symbol symbol = iterator.next();
            if (!symbol.isExternalEntryPoint() || !symbol.getAddress().isMemoryAddress()) {
                continue;
            }
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("name", symbol.getName());
            item.put("address", formatAddress(symbol.getAddress()));
            candidates.put(symbol.getName(), item);
        }
        if (expectedExports.isEmpty()) {
            List<Map<String, Object>> all = new ArrayList<>(candidates.values());
            all.sort(Comparator.comparing(item -> String.valueOf(item.get("name"))));
            return all;
        }
        List<Map<String, Object>> expected = new ArrayList<>();
        for (String name : expectedExports) {
            if (candidates.containsKey(name)) {
                expected.add(candidates.get(name));
            }
        }
        expected.sort(Comparator.comparing(item -> String.valueOf(item.get("name"))));
        return expected;
    }

    private List<Map<String, Object>> collectFunctions(List<String> expectedExports) {
        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        List<Map<String, Object>> result = new ArrayList<>();
        Set<String> exportNames = new LinkedHashSet<>(expectedExports);
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Function function = iterator.next();
            if (function.isExternal()) {
                continue;
            }
            Map<String, Object> symbol = new LinkedHashMap<>();
            symbol.put("name", function.getName());
            symbol.put("address", formatAddress(function.getEntryPoint()));
            symbol.put("size", function.getBody().getNumAddresses());
            symbol.put("type", exportNames.contains(function.getName())
                ? "exported_function" : "function");
            result.add(symbol);
        }
        result.sort(Comparator.comparing(item -> String.valueOf(item.get("address"))));
        return result;
    }

    // ---- strings of interest ----

    private List<StringRecord> collectStringsOfInterest(List<String> searchTerms) throws Exception {
        Map<String, StringRecord> unique = new LinkedHashMap<>();
        collectDefinedStrings(unique, searchTerms);
        collectRawAsciiStrings(unique, searchTerms);
        collectRawUtf16Strings(unique, searchTerms);
        List<StringRecord> result = new ArrayList<>(unique.values());
        result.sort(Comparator.comparing(record -> record.address));
        return result;
    }

    private void collectDefinedStrings(Map<String, StringRecord> unique, List<String> searchTerms) {
        DataIterator iterator = currentProgram.getListing().getDefinedData(true);
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Data data = iterator.next();
            if (!data.hasStringValue()) {
                continue;
            }
            Object rawValue = data.getValue();
            String value = rawValue == null
                ? data.getDefaultValueRepresentation() : rawValue.toString();
            List<String> matches = matchedTerms(value, searchTerms);
            if (matches.isEmpty()) {
                continue;
            }
            String type = data.getDataType() == null
                ? "defined-string" : data.getDataType().getDisplayName();
            addStringRecord(unique, new StringRecord(value, data.getAddress(), type,
                Math.max(1, data.getLength()), matches), true);
        }
    }

    private void collectRawAsciiStrings(Map<String, StringRecord> unique, List<String> searchTerms)
            throws Exception {
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            if (monitor.isCancelled() || !block.isInitialized()
                    || block.getSize() > Integer.MAX_VALUE) {
                continue;
            }
            byte[] bytes = readBlock(block);
            int start = -1;
            for (int index = 0; index <= bytes.length; index++) {
                boolean printable = index < bytes.length && isAsciiStringByte(bytes[index] & 0xff);
                if (printable && start < 0) {
                    start = index;
                }
                if (!printable && start >= 0) {
                    addAsciiRun(unique, block, bytes, start, index, searchTerms);
                    start = -1;
                }
            }
        }
    }

    private void addAsciiRun(Map<String, StringRecord> unique, MemoryBlock block, byte[] bytes,
            int start, int end, List<String> searchTerms) {
        int length = end - start;
        if (length < 4 || length > MAX_RAW_STRING_BYTES) {
            return;
        }
        String value = new String(bytes, start, length, java.nio.charset.StandardCharsets.US_ASCII);
        List<String> matches = matchedTerms(value, searchTerms);
        if (matches.isEmpty()) {
            return;
        }
        addStringRecord(unique, new StringRecord(value, block.getStart().add(start),
            "ascii-raw", length, matches), false);
    }

    private void collectRawUtf16Strings(Map<String, StringRecord> unique, List<String> searchTerms)
            throws Exception {
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            if (monitor.isCancelled() || !block.isInitialized()
                    || block.getSize() > Integer.MAX_VALUE) {
                continue;
            }
            byte[] bytes = readBlock(block);
            for (int phase = 0; phase < 2; phase++) {
                int start = -1;
                for (int index = phase; index + 1 <= bytes.length; index += 2) {
                    boolean printable = index + 1 < bytes.length
                        && isAsciiStringByte(bytes[index] & 0xff) && bytes[index + 1] == 0;
                    if (printable && start < 0) {
                        start = index;
                    }
                    if (!printable && start >= 0) {
                        addUtf16Run(unique, block, bytes, start, index, searchTerms);
                        start = -1;
                    }
                }
                if (start >= 0) {
                    addUtf16Run(unique, block, bytes, start,
                        bytes.length - ((bytes.length - start) % 2), searchTerms);
                }
            }
        }
    }

    private void addUtf16Run(Map<String, StringRecord> unique, MemoryBlock block, byte[] bytes,
            int start, int end, List<String> searchTerms) {
        int byteLength = end - start;
        if (byteLength < 8 || byteLength > MAX_RAW_STRING_BYTES) {
            return;
        }
        String value = new String(bytes, start, byteLength,
            java.nio.charset.StandardCharsets.UTF_16LE);
        List<String> matches = matchedTerms(value, searchTerms);
        if (matches.isEmpty()) {
            return;
        }
        addStringRecord(unique, new StringRecord(value, block.getStart().add(start),
            "utf16le-raw", byteLength, matches), false);
    }

    private byte[] readBlock(MemoryBlock block) throws Exception {
        int length = (int) block.getSize();
        byte[] bytes = new byte[length];
        int read = block.getBytes(block.getStart(), bytes);
        if (read == length) {
            return bytes;
        }
        return Arrays.copyOf(bytes, Math.max(0, read));
    }

    private void addStringRecord(Map<String, StringRecord> unique, StringRecord record,
            boolean preferNew) {
        String key = record.address.toString() + " " + record.value;
        if (preferNew || !unique.containsKey(key)) {
            unique.put(key, record);
        }
    }

    private List<String> matchedTerms(String value, List<String> searchTerms) {
        String lowered = value.toLowerCase(Locale.ROOT);
        List<String> matches = new ArrayList<>();
        for (String term : searchTerms) {
            if (lowered.contains(term.toLowerCase(Locale.ROOT))) {
                matches.add(term);
            }
        }
        return matches;
    }

    private boolean isAsciiStringByte(int value) {
        return value >= 0x20 && value <= 0x7e;
    }

    // ---- string referencing functions ----

    private Map<Function, List<StringRecord>> collectReferencingFunctions(
            List<StringRecord> strings) {
        FunctionManager functionManager = currentProgram.getFunctionManager();
        ReferenceManager referenceManager = currentProgram.getReferenceManager();
        Map<Function, List<StringRecord>> result = new LinkedHashMap<>();
        for (StringRecord record : strings) {
            int span = Math.min(Math.max(record.byteLength, 1), MAX_RAW_STRING_BYTES);
            Set<Function> functionsForString = new LinkedHashSet<>();
            for (int offset = 0; offset < span; offset++) {
                Address target;
                try {
                    target = record.address.add(offset);
                }
                catch (Exception exception) {
                    break;
                }
                ReferenceIterator references = referenceManager.getReferencesTo(target);
                while (references.hasNext()) {
                    Reference reference = references.next();
                    Function function = functionManager
                        .getFunctionContaining(reference.getFromAddress());
                    if (function != null && !function.isExternal()) {
                        functionsForString.add(function);
                    }
                }
            }
            for (Function function : functionsForString) {
                result.computeIfAbsent(function, ignored -> new ArrayList<>()).add(record);
            }
        }
        return result;
    }

    private List<Function> selectFocusFunctions(List<Map<String, Object>> exports,
            Map<Function, List<StringRecord>> references, List<String> focusTerms) {
        FunctionManager manager = currentProgram.getFunctionManager();
        Map<Address, Function> selected = new LinkedHashMap<>();
        for (Map<String, Object> export : exports) {
            String name = String.valueOf(export.get("name"));
            SymbolIterator symbols = currentProgram.getSymbolTable().getSymbols(name);
            while (symbols.hasNext()) {
                Function function = manager.getFunctionAt(symbols.next().getAddress());
                if (function != null && !function.isExternal()) {
                    selected.put(function.getEntryPoint(), function);
                }
            }
        }
        for (Map.Entry<Function, List<StringRecord>> entry : references.entrySet()) {
            if (isFocusReference(entry.getValue(), focusTerms)) {
                selected.put(entry.getKey().getEntryPoint(), entry.getKey());
            }
        }
        List<Function> result = new ArrayList<>(selected.values());
        result.sort(Comparator.comparing(Function::getEntryPoint));
        return result;
    }

    private boolean isFocusReference(List<StringRecord> records, List<String> focusTerms) {
        if (focusTerms.isEmpty()) {
            return true;
        }
        for (StringRecord record : records) {
            String lowered = record.value.toLowerCase(Locale.ROOT);
            for (String term : focusTerms) {
                if (lowered.contains(term.toLowerCase(Locale.ROOT))) {
                    return true;
                }
            }
        }
        return false;
    }

    // ---- decompile ----

    private List<Map<String, Object>> decompileFocusFunctions(List<Function> functions,
            Map<Function, List<StringRecord>> references, long maxDecompileBytes) {
        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.toggleSyntaxTree(true);
        decompiler.setSimplificationStyle("decompile");
        decompiler.openProgram(currentProgram);
        List<Map<String, Object>> result = new ArrayList<>();
        try {
            for (Function function : functions) {
                if (monitor.isCancelled()) {
                    break;
                }
                long size = function.getBody().getNumAddresses();
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("name", function.getName());
                item.put("address", formatAddress(function.getEntryPoint()));
                item.put("size", size);
                item.put("decompiled", size < maxDecompileBytes
                    ? decompile(function, decompiler) : null);
                item.put("referenced_strings", referencedStringMaps(references.get(function)));
                result.add(item);
            }
        }
        finally {
            decompiler.dispose();
        }
        return result;
    }

    private String decompile(Function function, DecompInterface decompiler) {
        try {
            DecompileResults results = decompiler.decompileFunction(
                function, DECOMPILE_TIMEOUT_SECONDS, monitor);
            if (results != null && results.decompileCompleted()
                    && results.getDecompiledFunction() != null) {
                return results.getDecompiledFunction().getC();
            }
            return null;
        }
        catch (Exception exception) {
            printerr("Decompile failed for " + function.getName() + ": "
                + exception.getMessage());
            return null;
        }
    }

    private List<Map<String, Object>> referencedStringMaps(List<StringRecord> records) {
        if (records == null) {
            return Collections.emptyList();
        }
        Map<String, Map<String, Object>> unique = new LinkedHashMap<>();
        for (StringRecord record : records) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("value", record.value);
            item.put("address", formatAddress(record.address));
            item.put("type", record.type);
            unique.put(record.address.toString() + " " + record.value, item);
        }
        return new ArrayList<>(unique.values());
    }

    private List<Map<String, Object>> functionNameMaps(List<Function> functions) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (Function function : functions) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("name", function.getName());
            item.put("address", formatAddress(function.getEntryPoint()));
            item.put("size", function.getBody().getNumAddresses());
            result.add(item);
        }
        return result;
    }

    private List<Map<String, Object>> toStringMaps(List<StringRecord> strings) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (StringRecord record : strings) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("value", record.value);
            item.put("address", formatAddress(record.address));
            item.put("type", record.type);
            item.put("matched_terms", record.matchedTerms);
            result.add(item);
        }
        return result;
    }

    // ---- suspicious API xrefs ----

    private List<Map<String, Object>> collectSuspiciousApiCalls() {
        SymbolTable symbolTable = currentProgram.getSymbolTable();
        FunctionManager functionManager = currentProgram.getFunctionManager();
        List<Map<String, Object>> result = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        SymbolIterator iterator = symbolTable.getExternalSymbols();
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Symbol symbol = iterator.next();
            String symName = symbol.getName();
            boolean suspicious = false;
            for (String sus : SUSPICIOUS_API) {
                if (symName.toLowerCase(Locale.ROOT).contains(sus.toLowerCase(Locale.ROOT))) {
                    suspicious = true;
                    break;
                }
            }
            if (!suspicious) {
                continue;
            }
            ReferenceIterator references = currentProgram.getReferenceManager()
                .getReferencesTo(symbol.getAddress());
            while (references.hasNext() && !monitor.isCancelled()) {
                Reference reference = references.next();
                String fromAddr = formatAddress(reference.getFromAddress());
                String key = symName + " " + fromAddr;
                if (seen.contains(key)) {
                    continue;
                }
                seen.add(key);
                Function caller = functionManager
                    .getFunctionContaining(reference.getFromAddress());
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("api", symName);
                item.put("api_dll", symbol.getParentNamespace() == null
                    ? "<unknown>" : symbol.getParentNamespace().getName());
                item.put("called_from_address", fromAddr);
                item.put("called_from_function", caller == null
                    ? "unknown" : caller.getName());
                item.put("type", "call");
                result.add(item);
            }
        }
        return result;
    }

    // ---- Go runtime / garble stats ----

    private List<Map<String, Object>> computeGoStats(List<Map<String, Object>> functions,
            String mode) {
        if (mode.equals("native")) {
            return Collections.emptyList();
        }
        boolean looksGo = false;
        for (Map<String, Object> fn : functions) {
            if (String.valueOf(fn.get("name")).startsWith("main.")) {
                looksGo = true;
                break;
            }
        }
        if (mode.equals("auto") && !looksGo) {
            return Collections.emptyList();
        }
        int runtimeCount = 0;
        int userCount = 0;
        int garbleCount = 0;
        List<Map<String, Object>> garbleFunctions = new ArrayList<>();
        for (Map<String, Object> fn : functions) {
            String name = String.valueOf(fn.get("name"));
            String fullName = name;
            if (isGoRuntime(fullName)) {
                runtimeCount++;
            }
            else {
                userCount++;
            }
            if (isGarbleObfuscated(fullName)) {
                Map<String, Object> item = new LinkedHashMap<>(fn);
                item.put("package", packageOf(fullName));
                garbleFunctions.add(item);
                garbleCount++;
            }
        }
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("mode", looksGo ? "go" : "auto");
        stats.put("go_runtime_function_count", runtimeCount);
        stats.put("user_function_count", userCount);
        stats.put("garble_obfuscated_count", garbleCount);
        stats.put("garble_obfuscated_functions", garbleFunctions);
        List<Map<String, Object>> result = new ArrayList<>();
        result.add(stats);
        return result;
    }

    private boolean isGoRuntime(String pkgName) {
        if (pkgName == null || pkgName.isEmpty()) {
            return false;
        }
        String topPkg = pkgName;
        int dotIdx = pkgName.indexOf('.');
        if (dotIdx > 0) {
            topPkg = pkgName.substring(0, dotIdx);
        }
        if (RUNTIME_PFX.contains(topPkg)) {
            return true;
        }
        for (String pfx : RUNTIME_PFX) {
            if (pkgName.startsWith(pfx + ".") || pkgName.equals(pfx)) {
                return true;
            }
        }
        return false;
    }

    private boolean isGarbleObfuscated(String funcName) {
        if (funcName == null || !funcName.startsWith("main.")) {
            return false;
        }
        if (!GARBLE_PATTERN.matcher(funcName).matches()) {
            return false;
        }
        String suffix = funcName.substring(5);
        boolean hasUpper = false;
        boolean hasLower = false;
        boolean hasDigit = false;
        for (char c : suffix.toCharArray()) {
            if (Character.isUpperCase(c)) {
                hasUpper = true;
            }
            else if (Character.isLowerCase(c)) {
                hasLower = true;
            }
            else if (Character.isDigit(c)) {
                hasDigit = true;
            }
        }
        return (hasUpper && hasLower) || (hasUpper && hasDigit)
            || (suffix.length() >= 5 && !suffix.matches("^[a-z]+$"));
    }

    private String packageOf(String fullName) {
        int dotIdx = fullName.indexOf('.');
        return dotIdx > 0 ? fullName.substring(0, dotIdx) : "";
    }

    // ---- findings ----

    private List<String> buildFindings(List<String> searchTerms,
            List<Map<String, Object>> imports, List<Map<String, Object>> exports,
            List<Map<String, Object>> functions, List<StringRecord> strings,
            List<Map<String, Object>> suspiciousCalls, List<Function> focusFunctions,
            List<Map<String, Object>> decompiled) {
        List<String> findings = new ArrayList<>();
        for (String term : searchTerms) {
            List<StringRecord> hits = findStrings(strings, term);
            findings.add(hits.isEmpty()
                ? "search term '" + term + "' not recovered among defined/raw strings."
                : "search term '" + term + "' recovered at "
                    + joinAddresses(hits) + " (" + hits.size() + " hit(s)).");
        }
        findings.add("imports=" + imports.size()
            + " exports=" + exports.size()
            + " functions=" + functions.size()
            + " suspicious_api_calls=" + suspiciousCalls.size());
        findings.add("focused functions selected: " + focusFunctions.size()
            + " (export entry points + string referrers); decompiled=" + decompiled.size());
        return findings;
    }

    private List<StringRecord> findStrings(List<StringRecord> strings, String needle) {
        String loweredNeedle = needle.toLowerCase(Locale.ROOT);
        List<StringRecord> result = new ArrayList<>();
        for (StringRecord record : strings) {
            if (record.value.toLowerCase(Locale.ROOT).contains(loweredNeedle)) {
                result.add(record);
            }
        }
        return result;
    }

    private String joinAddresses(List<StringRecord> records) {
        List<String> addresses = new ArrayList<>();
        for (StringRecord record : records) {
            addresses.add(formatAddress(record.address));
        }
        return String.join(", ", addresses);
    }
}
