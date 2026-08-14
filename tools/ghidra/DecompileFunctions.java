// DecompileFunctions.java — decompile functions / locate strings postScript (issue #293).
//
// Parameterized version of the verify-customer-feedback decompiler. The Jython
// runtime-annotation trap from the source is removed; this is pure Java with the
// unified --key=value arg style and UTF-8 JSON output.
//
// Args:
//   --addresses=0x...,0x...   VAs: find containing function, decompile + disasm window
//   --strings=a,b,...         search string definition + xrefs
//   --out=<abs path>          JSON report (absolute; parent dirs auto-created)
//   --window=<bytes>          disasm bytes before/after each target (default 0x80)
//   --context                 (issue #306) per address target, additionally emit
//                             caller/callee ~10-line decompiled snippets, xref'd
//                             strings inside the function body, and already-recovered
//                             (non-auto) names of those functions — the LLM reading
//                             context recipe (kong analyzer.py:208-348 technique,
//                             fresh implementation). Default output is unchanged
//                             without this flag.
//
// Output JSON schema: ghidra_decompile.v1 with program / image_base.

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class DecompileFunctions extends GhidraJsonScript {

    private static final int SNIPPET_LINES = 10;
    private static final int RELATIVE_LIMIT = 5;
    private static final int STRING_LIMIT = 50;
    // Ghidra auto-generated function-name prefixes — anything else counts as
    // an already-recovered (user/script-applied) name.
    private static final String[] AUTO_NAME_PREFIXES = {
        "FUN_", "LAB_", "DAT_", "SUB_", "thunk_"
    };

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        List<Long> addresses = new ArrayList<>();
        List<String> strings = new ArrayList<>();
        long window = 0x80;
        boolean contextEnabled = false;
        for (String arg : args) {
            if (arg.startsWith("--addresses=")) {
                for (String part : arg.substring("--addresses=".length()).split(",")) {
                    String trimmed = part.trim();
                    if (!trimmed.isEmpty()) {
                        addresses.add(Long.decode(trimmed));
                    }
                }
            }
            else if (arg.startsWith("--strings=")) {
                for (String part : arg.substring("--strings=".length()).split(",")) {
                    String trimmed = part.trim();
                    if (!trimmed.isEmpty()) {
                        strings.add(trimmed);
                    }
                }
            }
            else if (arg.startsWith("--window=")) {
                window = Long.decode(arg.substring("--window=".length()));
            }
            else if (arg.equals("--context") || arg.equals("--context=true")) {
                contextEnabled = true;
            }
        }
        String outPath = getArg(args, "out",
            System.getProperty("java.io.tmpdir") + "/decompile_functions.json");

        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
        List<Map<String, Object>> targets = new ArrayList<>();
        for (String query : strings) {
            targets.add(searchString(query));
        }
        for (long value : addresses) {
            targets.add(analyzeAddress(space.getAddress(value), window, contextEnabled));
        }

        Map<String, Object> root = new LinkedHashMap<>();
        root.putAll(meta("ghidra_decompile.v1", "DecompileFunctions.java"));
        root.put("target_count", targets.size());
        root.put("targets", targets);

        writeJson(outPath, root);
        println("DecompileFunctions: wrote " + outPath);
    }

    private Map<String, Object> analyzeAddress(Address addr, long window,
                                               boolean contextEnabled) {
        FunctionManager functionManager = currentProgram.getFunctionManager();
        Map<String, Object> target = new LinkedHashMap<>();
        target.put("kind", "address");
        target.put("address", formatAddress(addr));
        Function function = functionManager.getFunctionContaining(addr);
        if (function == null) {
            function = functionManager.getFunctionAt(addr);
        }
        if (function == null) {
            target.put("function", null);
            Instruction instruction = currentProgram.getListing().getInstructionAt(addr);
            if (instruction != null) {
                target.put("raw_instruction", instruction.toString());
                target.put("raw_bytes", hexBytes(instruction));
            }
            else {
                target.put("raw_instruction", "(no function / no instruction at this address)");
            }
            return target;
        }
        target.put("function", function.getName());
        target.put("entry", formatAddress(function.getEntryPoint()));
        target.put("end", formatAddress(function.getBody().getMaxAddress()));
        target.put("body_ranges", function.getBody().getNumAddressRanges());
        List<String> symbols = new ArrayList<>();
        Symbol[] symbolArray = currentProgram.getSymbolTable().getSymbols(function.getEntryPoint());
        for (Symbol symbol : symbolArray) {
            symbols.add(symbol.getName() + " [" + symbol.getSymbolType() + "]");
        }
        target.put("symbols", symbols);
        target.put("decompiled_c", decompile(function));
        target.put("disasm_window", disasmWindow(function, addr, window));
        if (contextEnabled) {
            try {
                target.put("context", buildContext(function));
            }
            catch (Exception e) {
                Map<String, Object> err = new LinkedHashMap<>();
                err.put("error", "context assembly failed: " + e.getMessage());
                target.put("context", err);
            }
        }
        return target;
    }

    // --context mode (issue #306): caller/callee snippets + xref'd strings +
    // already-recovered names, collected mechanically; the Python wrapper
    // assembles the LLM-ready document from these fields.
    private Map<String, Object> buildContext(Function function) {
        Map<String, Object> context = new LinkedHashMap<>();

        List<Map<String, Object>> callers = new ArrayList<>();
        Map<Long, Boolean> seenCallers = new HashMap<>();
        ReferenceIterator refsTo = currentProgram.getReferenceManager()
            .getReferencesTo(function.getEntryPoint());
        while (refsTo.hasNext() && callers.size() < RELATIVE_LIMIT) {
            Reference reference = refsTo.next();
            Function caller = currentProgram.getFunctionManager()
                .getFunctionContaining(reference.getFromAddress());
            if (caller == null
                || caller.getEntryPoint().equals(function.getEntryPoint())) {
                continue;
            }
            long entry = caller.getEntryPoint().getOffset();
            if (seenCallers.containsKey(entry)) {
                continue;
            }
            seenCallers.put(entry, true);
            callers.add(snippetEntry(caller));
        }
        context.put("callers", callers);

        List<Map<String, Object>> callees = new ArrayList<>();
        Map<Long, Boolean> seenCallees = new HashMap<>();
        java.util.Iterator<Instruction> instructions =
            currentProgram.getListing().getInstructions(function.getBody(), true);
        while (instructions.hasNext() && callees.size() < RELATIVE_LIMIT) {
            Instruction instruction = instructions.next();
            for (Reference reference : instruction.getReferencesFrom()) {
                Function callee = currentProgram.getFunctionManager()
                    .getFunctionAt(reference.getToAddress());
                if (callee == null
                    || callee.getEntryPoint().equals(function.getEntryPoint())) {
                    continue;
                }
                long entry = callee.getEntryPoint().getOffset();
                if (seenCallees.containsKey(entry)) {
                    continue;
                }
                seenCallees.put(entry, true);
                callees.add(snippetEntry(callee));
                if (callees.size() >= RELATIVE_LIMIT) {
                    break;
                }
            }
        }
        context.put("callees", callees);

        List<Map<String, Object>> xrefStrings = new ArrayList<>();
        // r1-306: collect strings REFERENCED FROM the function (e.g. .rdata
        // literals targeted by instructions in the body) — not data defined
        // inside the body itself.
        Map<String, Boolean> seenXrefStrings = new HashMap<>();
        ReferenceManager refMgr = currentProgram.getReferenceManager();
        for (Address fromAddr : function.getBody().getAddresses(true)) {
            for (Reference ref : refMgr.getReferencesFrom(fromAddr)) {
                if (xrefStrings.size() >= STRING_LIMIT) {
                    break;
                }
                Address toAddr = ref.getToAddress();
                Data data = currentProgram.getListing().getDataAt(toAddr);
                if (data == null || !(data.getValue() instanceof String)) {
                    continue;
                }
                String key = toAddr.toString();
                if (seenXrefStrings.containsKey(key)) {
                    continue;
                }
                seenXrefStrings.put(key, true);
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("address", formatAddress(toAddr));
                item.put("value", String.valueOf(data.getValue()));
                xrefStrings.add(item);
            }
            if (xrefStrings.size() >= STRING_LIMIT) {
                break;
            }
        }
        context.put("xref_strings", xrefStrings);

        List<Map<String, Object>> recoveredNames = new ArrayList<>();
        Map<Long, Boolean> seenNames = new HashMap<>();
        for (List<Map<String, Object>> group : Arrays.asList(callers, callees)) {
            for (Map<String, Object> item : group) {
                String name = String.valueOf(item.get("function"));
                long entry;
                try {
                    entry = Long.decode(String.valueOf(item.get("address")));
                }
                catch (NumberFormatException e) {
                    continue;
                }
                if (seenNames.containsKey(entry)) {
                    continue;
                }
                seenNames.put(entry, true);
                boolean auto = false;
                for (String prefix : AUTO_NAME_PREFIXES) {
                    if (name.startsWith(prefix)) {
                        auto = true;
                        break;
                    }
                }
                if (!auto) {
                    Map<String, Object> nm = new LinkedHashMap<>();
                    nm.put("address", item.get("address"));
                    nm.put("name", name);
                    recoveredNames.add(nm);
                }
            }
        }
        context.put("recovered_names", recoveredNames);
        return context;
    }

    private Map<String, Object> snippetEntry(Function function) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("address", formatAddress(function.getEntryPoint()));
        item.put("function", function.getName());
        item.put("snippet", headLines(decompile(function), SNIPPET_LINES));
        return item;
    }

    private String headLines(String text, int limit) {
        if (text == null || text.isEmpty()) {
            return "";
        }
        String[] lines = text.split("\n", -1);
        if (lines.length <= limit) {
            return text;
        }
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < limit; i++) {
            if (i > 0) {
                sb.append("\n");
            }
            sb.append(lines[i]);
        }
        return sb.toString();
    }

    private Map<String, Object> searchString(String query) {
        Map<String, Object> target = new LinkedHashMap<>();
        target.put("kind", "string");
        target.put("query", query);
        List<Map<String, Object>> hits = new ArrayList<>();
        Listing listing = currentProgram.getListing();
        DataIterator iterator = listing.getDefinedData(true);
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Data data = iterator.next();
            Object value = data.getValue();
            if (value instanceof String && ((String) value).contains(query)) {
                hits.add(stringHit(data.getAddress(), String.valueOf(value)));
            }
        }
        if (hits.isEmpty()) {
            hits.addAll(rawByteScan(query));
        }
        target.put("hits", hits);
        return target;
    }

    private Map<String, Object> stringHit(Address address, String value) {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("address", formatAddress(address));
        hit.put("value", value);
        hit.put("xrefs", getXrefsTo(address));
        return hit;
    }

    private List<Map<String, Object>> rawByteScan(String query) {
        List<Map<String, Object>> hits = new ArrayList<>();
        byte[] pattern;
        try {
            pattern = query.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        }
        catch (Exception e) {
            pattern = query.getBytes();
        }
        if (pattern.length == 0) {
            return hits;
        }
        try {
            for (ghidra.program.model.mem.MemoryBlock block
                    : currentProgram.getMemory().getBlocks()) {
                if (block.getSize() <= 0 || block.getSize() > Integer.MAX_VALUE) {
                    continue;
                }
                byte[] memory = new byte[(int) block.getSize()];
                block.getBytes(block.getStart(), memory);
                for (int i = 0; i + pattern.length <= memory.length; i++) {
                    boolean match = true;
                    for (int j = 0; j < pattern.length; j++) {
                        if (memory[i + j] != pattern[j]) {
                            match = false;
                            break;
                        }
                    }
                    if (match) {
                        Address here = block.getStart().add(i);
                        Map<String, Object> hit = new LinkedHashMap<>();
                        hit.put("address", formatAddress(here));
                        hit.put("value", query);
                        hit.put("raw", true);
                        hit.put("xrefs", getXrefsTo(here));
                        hits.add(hit);
                    }
                }
            }
        }
        catch (Exception e) {
            Map<String, Object> error = new LinkedHashMap<>();
            error.put("error", "byte-scan failed: " + e.getMessage());
            hits.add(error);
        }
        return hits;
    }

    private List<Map<String, Object>> getXrefsTo(Address addr) {
        List<Map<String, Object>> list = new ArrayList<>();
        ReferenceIterator iterator = currentProgram.getReferenceManager().getReferencesTo(addr);
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Reference reference = iterator.next();
            Function function = currentProgram.getFunctionManager()
                .getFunctionContaining(reference.getFromAddress());
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("ref_type", reference.getReferenceType().getName());
            item.put("from", formatAddress(reference.getFromAddress()));
            item.put("function", function == null ? "?" : function.getName());
            list.add(item);
        }
        return list;
    }

    private String decompile(Function function) {
        DecompInterface decompiler = new DecompInterface();
        try {
            if (!decompiler.openProgram(currentProgram)) {
                return "DecompInterface.openProgram failed";
            }
            decompiler.toggleCCode(true);
            DecompileResults results = decompiler.decompileFunction(function, 120, monitor);
            if (results != null && results.decompileCompleted()) {
                return results.getDecompiledFunction().getC();
            }
            return "decompile FAILED: "
                + (results != null ? results.getErrorMessage() : "null result");
        }
        finally {
            decompiler.dispose();
        }
    }

    private String hexBytes(Instruction instruction) {
        try {
            byte[] bytes = instruction.getBytes();
            StringBuilder sb = new StringBuilder();
            for (byte b : bytes) {
                sb.append(String.format("%02x", b & 0xFF));
            }
            return sb.toString();
        }
        catch (Exception e) {
            return "";
        }
    }

    private String disasmWindow(Function function, Address target, long window) {
        Listing listing = currentProgram.getListing();
        Address start = function.getBody().getMinAddress();
        Address end = function.getBody().getMaxAddress();
        Address lo = target.subtract(window);
        Address hi = target.add(window);
        if (lo.compareTo(start) < 0) {
            lo = start;
        }
        if (hi.compareTo(end) > 0) {
            hi = end;
        }
        StringBuilder sb = new StringBuilder();
        Address cursor = lo;
        while (cursor != null && cursor.compareTo(hi) <= 0) {
            Instruction instruction = listing.getInstructionAt(cursor);
            if (instruction != null) {
                String marker = cursor.equals(target) ? " <<<TARGET" : "";
                sb.append(String.format("  %s: %-28s %s%s%n", instruction.getAddress(),
                    hexBytes(instruction), instruction.toString(), marker));
                cursor = instruction.getMinAddress().add(instruction.getLength());
            }
            else {
                sb.append("  ").append(cursor).append(": (data/undefined)\n");
                cursor = cursor.add(1);
            }
        }
        return sb.toString();
    }
}
