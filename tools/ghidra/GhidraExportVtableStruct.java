// GhidraExportVtableStruct.java — export / annotate a vtable-like callback table (issue #293).
//
// Adapted from the sa-ghidra vtable exporter: headless, parameterized via
// --key=value args (unified #293 style), emits UTF-8 JSON with
// schema/program/image_base, and can apply labels/comments/structure when
// --apply=true. Stops at a neighboring vtable symbol boundary when Ghidra
// exposes one.
//
// Args:
//   --address=<va>            start address of the vtable (also accepts --start)
//   --out=<abs path>          JSON output (default: <project>/ghidra_vtable_export.json)
//   --name=<id>               vtable name (default anonymous_vtable)
//   --class=<id>              owning class name (default from symbol parent)
//   --category=<path>         data-type category for applied struct
//   --max=<n>                 max entries (default 64)
//   --apply=true|false        apply struct/labels/comments into the program
//
// Output schema: ghidra_vtable_struct.v1.

import ghidra.app.util.demangler.Demangled;
import ghidra.app.util.demangler.DemangledFunction;
import ghidra.app.util.demangler.DemangledObject;
import ghidra.app.util.demangler.DemanglerUtil;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.CategoryPath;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.StructureDataType;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class GhidraExportVtableStruct extends GhidraJsonScript {

    private static final class Entry {
        int index;
        Address slotAddress;
        Address targetAddress;
        String functionName;
        String fieldName;
        boolean hasFunction;
    }

    private Address readPointer(Address tableEntry) throws Exception {
        int pointerSize = currentProgram.getDefaultPointerSize();
        long raw;
        if (pointerSize == 4) {
            raw = Integer.toUnsignedLong(getInt(tableEntry));
        }
        else {
            raw = getLong(tableEntry);
        }
        return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(raw);
    }

    private String sanitizeName(String value, String fallback) {
        if (value == null || value.length() == 0) {
            value = fallback;
        }
        String cleaned = value.replaceAll("[^A-Za-z0-9_]", "_");
        if (cleaned.length() == 0) {
            cleaned = fallback;
        }
        if (!Character.isLetter(cleaned.charAt(0)) && cleaned.charAt(0) != '_') {
            cleaned = "_" + cleaned;
        }
        return cleaned;
    }

    private String symbolParentName(Address addr) {
        Symbol symbol = getSymbolAt(addr);
        if (symbol == null) {
            return "";
        }
        Symbol parent = symbol.getParentSymbol();
        return parent == null ? "" : parent.getName();
    }

    private String defaultClassName(Address start, String fallback) {
        String parent = symbolParentName(start);
        return parent.length() > 0 ? parent : fallback;
    }

    private String bestFunctionFieldName(Function function, String className, int index) {
        String funcName = function == null ? "" : function.getName();
        if (function != null && className != null && className.length() > 0) {
            Symbol[] symbols = currentProgram.getSymbolTable()
                .getSymbols(function.getEntryPoint());
            for (Symbol symbol : symbols) {
                try {
                    DemangledObject demangled = DemanglerUtil.demangle(symbol.getName());
                    if (demangled instanceof DemangledFunction) {
                        DemangledFunction demangledFunction = (DemangledFunction) demangled;
                        Demangled namespace = demangledFunction.getNamespace();
                        if (namespace != null && namespace.getName().equals(className)) {
                            funcName = demangledFunction.getName();
                            break;
                        }
                    }
                }
                catch (Exception ignored) {
                }
                Symbol parent = symbol.getParentSymbol();
                if (parent != null && parent.getName().contains(className)) {
                    funcName = symbol.getName();
                    break;
                }
            }
        }
        return sanitizeName("slot_" + index + "_" + funcName, "slot_" + index);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Address start = toAddr(getArg(args, "address", getArg(args, "start", "")));
        String output = getArg(args, "out",
            System.getProperty("java.io.tmpdir") + "/ghidra_vtable_export.json");
        String name = getArg(args, "name", "anonymous_vtable");
        String className = getArg(args, "class", defaultClassName(start, "anonymous"));
        String categoryName = getArg(args, "category", "/analysis_vtables");
        int maxEntries = Integer.parseInt(getArg(args, "max", "64"));
        boolean apply = getBoolArg(args, "apply", false);
        int pointerSize = currentProgram.getDefaultPointerSize();
        String terminationReason = "max_entries";

        List<Entry> entries = new ArrayList<>();
        Address cursor = start;
        for (int i = 0; i < maxEntries; i++) {
            if (i > 0) {
                String parent = symbolParentName(cursor);
                if (parent.length() > 0 && className.length() > 0 && !parent.equals(className)) {
                    terminationReason = "neighbor_vtable_symbol_boundary";
                    break;
                }
            }
            Entry entry = new Entry();
            entry.index = i;
            entry.slotAddress = cursor;
            entry.targetAddress = readPointer(cursor);
            Function function = getFunctionAt(entry.targetAddress);
            entry.hasFunction = function != null;
            entry.functionName = function == null ? "" : function.getName();
            if (!entry.hasFunction) {
                terminationReason = "non_function_pointer";
                break;
            }
            entry.fieldName = bestFunctionFieldName(function, className, i);
            entries.add(entry);
            cursor = cursor.add(pointerSize);
        }

        if (apply && entries.size() > 0) {
            applyStructure(start, name, className, categoryName, pointerSize, entries);
        }

        Map<String, Object> root = new LinkedHashMap<>();
        root.putAll(meta("ghidra_vtable_struct.v1", "GhidraExportVtableStruct.java"));
        root.put("vtable_name", name);
        root.put("class_name", className);
        root.put("address", formatAddress(start));
        root.put("pointer_size", pointerSize);
        root.put("applied", apply);
        root.put("termination_reason", terminationReason);
        root.put("entry_count", entries.size());
        List<Map<String, Object>> entryMaps = new ArrayList<>();
        for (Entry entry : entries) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("index", entry.index);
            item.put("slot_address", formatAddress(entry.slotAddress));
            item.put("target_address", formatAddress(entry.targetAddress));
            item.put("function", entry.functionName);
            item.put("field", entry.fieldName);
            entryMaps.add(item);
        }
        root.put("entries", entryMaps);

        writeJson(output, root);
        println("GhidraExportVtableStruct: wrote " + output);
    }

    private void applyStructure(Address start, String name, String className,
            String categoryName, int pointerSize, List<Entry> entries) throws Exception {
        DataTypeManager dtm = currentProgram.getDataTypeManager();
        CategoryPath category = new CategoryPath(categoryName);
        if (dtm.getCategory(category) == null) {
            dtm.createCategory(category);
        }
        String typeName = sanitizeName(name, "anonymous_vtable");
        StructureDataType struct = new StructureDataType(category, typeName, 0, dtm);
        DataType voidPtr = dtm.getPointer(null, pointerSize);
        for (Entry entry : entries) {
            struct.insertAtOffset(entry.index * pointerSize, voidPtr, pointerSize,
                entry.fieldName, entry.functionName);
        }
        DataType installedType = dtm.addDataType(struct, DataTypeConflictHandler.REPLACE_HANDLER);

        Listing listing = currentProgram.getListing();
        Address end = start.add((long) entries.size() * pointerSize - 1);
        listing.clearCodeUnits(start, end, false);
        listing.createData(start, installedType, entries.size() * pointerSize);
        createLabel(start, name, true, SourceType.USER_DEFINED);
        setPlateComment(start, "Recovered callback/vtable structure: " + name
            + "; class=" + className + "; entries=" + entries.size());
        for (Entry entry : entries) {
            listing.setComment(entry.targetAddress, CodeUnit.PRE_COMMENT,
                "Referenced by " + name + " slot " + entry.index
                    + " at " + entry.slotAddress);
        }
    }
}
