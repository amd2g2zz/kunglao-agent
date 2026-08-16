// GhidraScanPointer.java — xref-to-address / scan-address-window postScript (issue #293).
//
// Merges the XrefToAddress and ScanAddrWindow postScripts into one tool with a
// --mode switch, sharing the GhidraJsonScript base (arg parsing, JSON writer,
// schema/program/image_base metadata).
//
// Args:
//   --mode=xref|window        xref: dump refs to specific addresses;
//                             window: scan memory for 8-byte LE pointers into a range
//   --out=<abs path>          JSON output (default: <project>/scan_pointer.json)
//
// xref mode:
//   --addresses=0x...,0x...   VAs to query (absolute, image-based)
//   --bytes=<n>               bytes to dump at each addr (default 32)
//
// window mode:
//   --center=0x...            address of interest (an entry in a table)
//   --window=0x...            +/- byte range around center treated as "in table"
//
// Output schema: ghidra_scan_pointer.v1.

import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

public class GhidraScanPointer extends GhidraJsonScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String mode = getArg(args, "mode", "xref").toLowerCase(java.util.Locale.ROOT);
        String outPath = getArg(args, "out",
            System.getProperty("java.io.tmpdir") + "/scan_pointer.json");

        Map<String, Object> root = new LinkedHashMap<>();
        root.putAll(meta("ghidra_scan_pointer.v1", "GhidraScanPointer.java"));
        root.put("mode", mode);

        if (mode.equals("window")) {
            root.putAll(runWindow(args));
        }
        else {
            root.putAll(runXref(args));
        }

        writeJson(outPath, root);
        println("GhidraScanPointer[" + mode + "]: wrote " + outPath);
    }

    // ---- xref mode (XrefToAddress) ----

    private Map<String, Object> runXref(String[] args) {
        List<Long> addresses = new ArrayList<>();
        int nbytes = 32;
        for (String arg : args) {
            if (arg.startsWith("--addresses=")) {
                for (String part : arg.substring("--addresses=".length()).split(",")) {
                    String trimmed = part.trim();
                    if (!trimmed.isEmpty()) {
                        addresses.add(Long.decode(trimmed));
                    }
                }
            }
            else if (arg.startsWith("--bytes=")) {
                nbytes = Integer.decode(arg.substring("--bytes=".length()));
            }
        }
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
        List<Map<String, Object>> targets = new ArrayList<>();
        for (long value : addresses) {
            targets.add(analyzeXref(space.getAddress(value), nbytes, value));
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("target_count", targets.size());
        body.put("targets", targets);
        return body;
    }

    private Map<String, Object> analyzeXref(Address addr, int nbytes, long addrVal) {
        Map<String, Object> target = new LinkedHashMap<>();
        target.put("address", formatAddress(addr));
        target.put("block", blockKind(addr));

        SymbolTable symbolTable = currentProgram.getSymbolTable();
        List<String> symbols = new ArrayList<>();
        for (Symbol symbol : symbolTable.getSymbols(addr)) {
            symbols.add(symbol.getName() + " [" + symbol.getSymbolType()
                + "] namespace=" + symbol.getParentNamespace().getName());
        }
        target.put("symbols", symbols);

        Listing listing = currentProgram.getListing();
        Data data = listing.getDataAt(addr);
        if (data != null) {
            target.put("data_type", data.getDataType().getName());
            target.put("data_length", data.getLength());
            target.put("data_value", data.getValue() == null ? null : data.getValue().toString());
        }
        else {
            target.put("data_type", "(undefined)");
        }
        target.put("bytes", dumpBytes(addr, nbytes));

        List<Map<String, Object>> references = dumpXrefsTo(addr);
        target.put("references", references);
        target.put("reference_count", references.size());

        target.put("raw_scan", rawScanForAddrConstant(addr, addrVal));
        return target;
    }

    private List<Map<String, Object>> dumpXrefsTo(Address addr) {
        ReferenceManager referenceManager = currentProgram.getReferenceManager();
        List<Map<String, Object>> rows = new ArrayList<>();
        ReferenceIterator iterator = referenceManager.getReferencesTo(addr);
        while (iterator.hasNext() && !monitor.isCancelled()) {
            Reference reference = iterator.next();
            RefType refType = reference.getReferenceType();
            Function function = currentProgram.getFunctionManager()
                .getFunctionContaining(reference.getFromAddress());
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("ref_type", refType.getName());
            item.put("from", formatAddress(reference.getFromAddress()));
            item.put("function", function == null
                ? null : function.getName() + "@" + formatAddress(function.getEntryPoint()));
            item.put("source", String.valueOf(reference.getSource()));
            item.put("primary", reference.isPrimary());
            rows.add(item);
        }
        return rows;
    }

    private Map<String, Object> rawScanForAddrConstant(Address target, long targetVal) {
        byte[] pattern = new byte[8];
        for (int i = 0; i < 8; i++) {
            pattern[i] = (byte) ((targetVal >>> (8 * i)) & 0xFF);
        }
        List<Map<String, Object>> hits = new ArrayList<>();
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            long size = block.getSize();
            if (size <= 0 || size > 0x8000000L) {
                continue;
            }
            byte[] memory;
            try {
                memory = new byte[(int) size];
                block.getBytes(block.getStart(), memory);
            }
            catch (Exception e) {
                continue;
            }
            for (int i = 0; i + 8 <= memory.length; i++) {
                boolean match = true;
                for (int j = 0; j < 8; j++) {
                    if (memory[i + j] != pattern[j]) {
                        match = false;
                        break;
                    }
                }
                if (match) {
                    Address hit = block.getStart().add(i);
                    Function function = currentProgram.getFunctionManager()
                        .getFunctionContaining(hit);
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("address", formatAddress(hit));
                    item.put("where", function == null
                        ? ("block " + blockKind(hit)) : (function.getName()
                            + "@" + formatAddress(function.getEntryPoint())));
                    hits.add(item);
                }
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("pattern", bytesHex(pattern));
        result.put("hits", hits);
        return result;
    }

    // ---- window mode (ScanAddrWindow) ----

    private Map<String, Object> runWindow(String[] args) {
        long center = 0;
        long window = 0;
        for (String arg : args) {
            if (arg.startsWith("--center=")) {
                center = Long.decode(arg.substring("--center=".length()));
            }
            else if (arg.startsWith("--window=")) {
                window = Long.decode(arg.substring("--window=".length()));
            }
        }
        long lo = center - window;
        long hi = center + window;
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Address loAddr = space.getAddress(lo);
        Address hiAddr = space.getAddress(hi);

        TreeMap<Long, List<String>> byValue = new TreeMap<>();
        int totalHits = 0;
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            long size = block.getSize();
            if (size <= 0 || size > 0x8000000L) {
                continue;
            }
            byte[] memory;
            try {
                memory = new byte[(int) size];
                block.getBytes(block.getStart(), memory);
            }
            catch (Exception e) {
                continue;
            }
            for (int i = 0; i + 8 <= memory.length; i++) {
                long value = 0;
                for (int j = 7; j >= 0; j--) {
                    value = (value << 8) | (memory[i + j] & 0xFFL);
                }
                if (value >= lo && value <= hi) {
                    Address hit = block.getStart().add(i);
                    Function function = currentProgram.getFunctionManager()
                        .getFunctionContaining(hit);
                    String location = formatAddress(hit) + "  block=" + block.getName()
                        + "  " + (function != null
                            ? ("in_fn=" + function.getName()
                                + "@" + formatAddress(function.getEntryPoint()))
                            : "(data/no-fn)");
                    boolean selfRegion = hit.compareTo(loAddr) >= 0 && hit.compareTo(hiAddr) <= 0;
                    if (selfRegion) {
                        location += " [SELF-REGION: a header's own ptr/len field]";
                    }
                    byValue.computeIfAbsent(value, k -> new ArrayList<>()).add(location);
                    totalHits++;
                }
            }
        }

        List<Map<String, Object>> hitList = new ArrayList<>();
        for (Map.Entry<Long, List<String>> entry : byValue.entrySet()) {
            List<String> locations = entry.getValue();
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("value", String.format("0x%016x", entry.getKey()));
            item.put("count", locations.size());
            item.put("locations", locations.subList(0, Math.min(5, locations.size())));
            hitList.add(item);
        }

        long codeHits = 0;
        for (List<String> locations : byValue.values()) {
            for (String location : locations) {
                if (location.contains("in_fn=")) {
                    codeHits++;
                }
            }
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("center", String.format("0x%x", center));
        body.put("window", String.format("0x%x", window));
        Map<String, String> range = new LinkedHashMap<>();
        range.put("lo", String.format("0x%x", lo));
        range.put("hi", String.format("0x%x", hi));
        body.put("search_range", range);
        body.put("total_hits", totalHits);
        body.put("distinct_values", byValue.size());
        body.put("code_hits", codeHits);
        body.put("values", hitList);
        return body;
    }

    // ---- shared helpers ----

    private String blockKind(Address addr) {
        MemoryBlock block = currentProgram.getMemory().getBlock(addr);
        if (block == null) {
            return "?";
        }
        String kind = block.isInitialized() ? "I" : "U";
        if (block.isRead()) {
            kind += "R";
        }
        if (block.isWrite()) {
            kind += "W";
        }
        if (block.isExecute()) {
            kind += "X";
        }
        return block.getName() + "(" + kind + ")";
    }

    private String dumpBytes(Address addr, int nbytes) {
        try {
            byte[] buffer = new byte[nbytes];
            currentProgram.getMemory().getBytes(addr, buffer);
            StringBuilder hexs = new StringBuilder();
            StringBuilder asc = new StringBuilder();
            for (byte b : buffer) {
                hexs.append(String.format("%02x", b & 0xFF)).append(" ");
                int value = b & 0xFF;
                asc.append((value >= 0x20 && value < 0x7F)
                    ? String.valueOf((char) value) : ".");
            }
            return hexs.toString().trim() + "  |" + asc.toString() + "|";
        }
        catch (Exception e) {
            return "(read failed: " + e.getMessage() + ")";
        }
    }

    private String bytesHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) {
            sb.append(String.format("%02x", b & 0xFF));
        }
        return sb.toString();
    }
}
