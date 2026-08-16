// GhidraEvidenceAnnotations.java — apply / verify evidence-backed annotations (issue #293).
//
// Merges the apply and verify evidence-annotation postScripts into one tool with
// a --mode switch. TSV columns (same as the sa-ghidra sources):
//   address<TAB>label<TAB>kind<TAB>comment
// Backslash escapes (\\t, \\n) in TSV fields are unescaped (shared getArg /
// unescape live in the GhidraJsonScript base).
//
// Args:
//   --mode=apply|verify       apply annotations or verify they landed (default apply)
//   --tsv=<abs path>          evidence annotations TSV (also accepts annotations=)
//   --out=<abs path>          JSON summary output (default: <project>/evidence_annotations.json)
//
// Output schema: ghidra_evidence_annotations.v1. In verify mode a mismatch
// throws, failing the postScript (fail-closed), and the JSON records the
// missing rows.

import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class GhidraEvidenceAnnotations extends GhidraJsonScript {

    private static final class Row {
        String address;
        String label;
        String kind;
        String comment;
    }

    private List<Row> readRows(File file) throws Exception {
        List<Row> rows = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
            String line;
            boolean first = true;
            while ((line = reader.readLine()) != null) {
                if (first) {
                    first = false;
                    continue;
                }
                if (line.trim().isEmpty()) {
                    continue;
                }
                String[] parts = line.split("\t", -1);
                if (parts.length < 4) {
                    continue;
                }
                Row row = new Row();
                row.address = unescape(parts[0]);
                row.label = unescape(parts[1]);
                row.kind = unescape(parts[2]);
                row.comment = unescape(parts[3]);
                rows.add(row);
            }
        }
        return rows;
    }

    // ---- apply ----

    private void applyLabel(Address addr, String name) {
        if (name == null || name.isEmpty()) {
            return;
        }
        try {
            SymbolTable symbols = currentProgram.getSymbolTable();
            Symbol wanted = null;
            for (Symbol symbol : symbols.getSymbols(addr)) {
                if (symbol.getName().equals(name)) {
                    wanted = symbol;
                    break;
                }
            }
            if (wanted == null) {
                wanted = symbols.createLabel(addr, name, SourceType.USER_DEFINED);
            }
            if (!wanted.isPrimary()) {
                Symbol primary = symbols.getPrimarySymbol(addr);
                if (primary == null || primary.getName().startsWith("FUN_")
                    || primary.getName().startsWith("LAB_")
                    || primary.getName().startsWith("DAT_")
                    || primary.getName().startsWith("PTR_")
                    || primary.getName().startsWith("thunk_")) {
                    wanted.setPrimary();
                }
            }
        }
        catch (Exception e) {
            println("label failed at " + addr + ": " + e.getMessage());
        }
    }

    private void renameFunctionIfGeneric(Address addr, String name) {
        if (name == null || name.isEmpty()) {
            return;
        }
        try {
            Function function = getFunctionAt(addr);
            if (function == null) {
                return;
            }
            String old = function.getName();
            if (old.startsWith("FUN_") || old.startsWith("thunk_FUN_")
                || old.startsWith("sub_")) {
                function.setName(name, SourceType.USER_DEFINED);
            }
        }
        catch (Exception e) {
            println("function rename failed at " + addr + ": " + e.getMessage());
        }
    }

    private Map<String, Object> applyAnnotations(List<Row> rows) {
        int applied = 0;
        for (Row row : rows) {
            Address addr = toAddr(row.address);
            String comment = "[EVIDENCE:" + row.kind + "] " + row.label + "\n" + row.comment;
            applyLabel(addr, row.label);
            renameFunctionIfGeneric(addr, row.label);
            currentProgram.getListing().setComment(addr, CodeUnit.PLATE_COMMENT, comment);
            currentProgram.getListing().setComment(addr, CodeUnit.PRE_COMMENT, comment);
            currentProgram.getBookmarkManager().setBookmark(addr, "Evidence", row.kind, row.label);
            applied++;
        }
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("mode", "apply");
        summary.put("rows", rows.size());
        summary.put("applied", applied);
        return summary;
    }

    // ---- verify ----

    private boolean hasLabel(Address addr, String expectedName) {
        for (Symbol candidate : currentProgram.getSymbolTable().getSymbols(addr)) {
            if (candidate.getName().equals(expectedName)) {
                return true;
            }
        }
        return false;
    }

    private boolean hasEvidenceComment(Address addr, String kind, String label) {
        String marker = "[EVIDENCE:" + kind + "]";
        String plate = currentProgram.getListing().getComment(CodeUnit.PLATE_COMMENT, addr);
        String pre = currentProgram.getListing().getComment(CodeUnit.PRE_COMMENT, addr);
        return (plate != null && plate.contains(marker) && plate.contains(label))
            || (pre != null && pre.contains(marker) && pre.contains(label));
    }

    private Map<String, Object> verifyAnnotations(List<Row> rows) {
        int rowsCount = 0;
        int labelsOk = 0;
        int commentsOk = 0;
        List<Map<String, Object>> missing = new ArrayList<>();
        for (Row row : rows) {
            rowsCount++;
            Address addr = toAddr(row.address);
            boolean labelOk = hasLabel(addr, row.label);
            boolean commentOk = hasEvidenceComment(addr, row.kind, row.label);
            if (labelOk) {
                labelsOk++;
            }
            if (commentOk) {
                commentsOk++;
            }
            if (!labelOk || !commentOk) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("address", row.address);
                item.put("label", row.label);
                item.put("kind", row.kind);
                item.put("label_ok", labelOk);
                item.put("comment_ok", commentOk);
                missing.add(item);
            }
        }
        boolean pass = labelsOk == rowsCount && commentsOk == rowsCount;
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("mode", "verify");
        summary.put("rows", rowsCount);
        summary.put("labels_ok", labelsOk);
        summary.put("comments_ok", commentsOk);
        summary.put("pass", pass);
        summary.put("missing", missing);
        if (!pass) {
            throw new RuntimeException("Missing evidence annotations: labels "
                + labelsOk + "/" + rowsCount + ", comments " + commentsOk + "/" + rowsCount);
        }
        return summary;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String mode = getArg(args, "mode", "apply").toLowerCase(java.util.Locale.ROOT);
        String tsvPath = getArg(args, "tsv", getArg(args, "annotations", ""));
        if (tsvPath.isEmpty()) {
            throw new IllegalArgumentException("Required arg: --tsv=<evidence annotations tsv>");
        }
        String outPath = getArg(args, "out",
            System.getProperty("java.io.tmpdir") + "/evidence_annotations.json");

        List<Row> rows = readRows(new File(tsvPath));
        Map<String, Object> summary;
        if (mode.equals("verify")) {
            summary = verifyAnnotations(rows);
        }
        else {
            summary = applyAnnotations(rows);
        }

        Map<String, Object> root = new LinkedHashMap<>();
        root.putAll(meta("ghidra_evidence_annotations.v1", "GhidraEvidenceAnnotations.java"));
        root.put("tsv", tsvPath);
        root.putAll(summary);

        writeJson(outPath, root);
        println("GhidraEvidenceAnnotations[" + mode + "]: wrote " + outPath
            + " (rows=" + rows.size() + ")");
    }
}
