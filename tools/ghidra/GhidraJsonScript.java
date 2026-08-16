// GhidraJsonScript.java — shared infrastructure for tools/ghidra/*.java (issue #293).
//
// Abstract base for the 5 parameterized Ghidra postScript tools:
//   - unified --key=value / key=value argument parsing (getArg/getBoolArg)
//   - shared TSV unescape (evidence-annotations)
//   - UTF-8, self-contained JSON writer (no org.json.simple dependency)
//   - absolute --out path with mkdirs
//   - schema/program/image_base metadata block
//
// Every concrete subclass in this directory implements run() and is invoked via
// analyzeHeadless -postScript <name>.java; this base is abstract and therefore
// not runnable as a script.

import ghidra.app.script.GhidraScript;
import ghidra.framework.Application;
import ghidra.program.model.address.Address;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;

public abstract class GhidraJsonScript extends GhidraScript {

    /** Read a --key=value / key=value script arg, falling back to defaultValue. */
    protected String getArg(String[] args, String key, String defaultValue) {
        String direct = key + "=";
        String dashed = "--" + key + "=";
        for (int i = 0; i < args.length; i++) {
            String arg = args[i];
            if (arg.startsWith(dashed)) {
                return arg.substring(dashed.length());
            }
            if (arg.startsWith(direct)) {
                return arg.substring(direct.length());
            }
            if ((arg.equals("--" + key) || arg.equals(key)) && i + 1 < args.length
                    && !args[i + 1].trim().isEmpty()) {
                return args[i + 1];
            }
        }
        return defaultValue;
    }

    /** Read a boolean --key=value script arg (true/1/yes case-insensitive). */
    protected boolean getBoolArg(String[] args, String key, boolean defaultValue) {
        String value = getArg(args, key, defaultValue ? "true" : "false");
        return value.equalsIgnoreCase("true") || value.equals("1") || value.equalsIgnoreCase("yes");
    }

    /** Unescape backslash escapes (\\n, \\t) in TSV fields (evidence-annotations). */
    protected String unescape(String text) {
        StringBuilder out = new StringBuilder();
        boolean esc = false;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (!esc && c == '\\') {
                esc = true;
                continue;
            }
            if (esc) {
                if (c == 'n') {
                    out.append('\n');
                }
                else if (c == 't') {
                    out.append('\t');
                }
                else {
                    out.append(c);
                }
                esc = false;
                continue;
            }
            out.append(c);
        }
        if (esc) {
            out.append('\\');
        }
        return out.toString();
    }

    /** Build the standard schema/program/image_base metadata block. */
    protected Map<String, Object> meta(String schema, String scriptName) {
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("schema", schema);
        meta.put("program", currentProgram.getName());
        meta.put("image_base", formatAddress(currentProgram.getImageBase()));
        meta.put("ghidra_version", Application.getApplicationVersion());
        meta.put("script", scriptName);
        meta.put("analyzed_at", Instant.now().toString());
        return meta;
    }

    /** 0x-prefixed address string; null-safe. */
    protected String formatAddress(Address address) {
        if (address == null) {
            return null;
        }
        return address.isMemoryAddress() ? "0x" + address : address.toString();
    }

    /** Write a UTF-8 JSON value to an absolute --out path, creating parent dirs. */
    protected void writeJson(String outputPath, Object value) throws Exception {
        File outputFile = new File(outputPath).getCanonicalFile();
        File parent = outputFile.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IllegalStateException("Unable to create output directory: " + parent);
        }
        try (BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(
                new FileOutputStream(outputFile), StandardCharsets.UTF_8))) {
            writeJsonValue(writer, value);
            writer.newLine();
        }
    }

    private void writeJsonValue(BufferedWriter writer, Object value) throws Exception {
        if (value == null) {
            writer.write("null");
        }
        else if (value instanceof String) {
            writer.write('"');
            writer.write(escapeJson((String) value));
            writer.write('"');
        }
        else if (value instanceof Number || value instanceof Boolean) {
            writer.write(value.toString());
        }
        else if (value instanceof Map<?, ?>) {
            writeJsonObject(writer, (Map<?, ?>) value);
        }
        else if (value instanceof Collection<?>) {
            writeJsonArray(writer, (Collection<?>) value);
        }
        else {
            writer.write('"');
            writer.write(escapeJson(value.toString()));
            writer.write('"');
        }
    }

    private void writeJsonObject(BufferedWriter writer, Map<?, ?> value) throws Exception {
        writer.write('{');
        boolean first = true;
        for (Map.Entry<?, ?> entry : value.entrySet()) {
            if (!first) {
                writer.write(',');
            }
            first = false;
            writer.write('"');
            writer.write(escapeJson(String.valueOf(entry.getKey())));
            writer.write("\":");
            writeJsonValue(writer, entry.getValue());
        }
        writer.write('}');
    }

    private void writeJsonArray(BufferedWriter writer, Collection<?> value) throws Exception {
        writer.write('[');
        boolean first = true;
        for (Object item : value) {
            if (!first) {
                writer.write(',');
            }
            first = false;
            writeJsonValue(writer, item);
        }
        writer.write(']');
    }

    private String escapeJson(String value) {
        StringBuilder escaped = new StringBuilder(value.length() + 16);
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '"': escaped.append("\\\""); break;
                case '\\': escaped.append("\\\\"); break;
                case '\b': escaped.append("\\b"); break;
                case '\f': escaped.append("\\f"); break;
                case '\n': escaped.append("\\n"); break;
                case '\r': escaped.append("\\r"); break;
                case '\t': escaped.append("\\t"); break;
                default:
                    if (character < 0x20) {
                        escaped.append(String.format("\\u%04x", (int) character));
                    }
                    else {
                        escaped.append(character);
                    }
            }
        }
        return escaped.toString();
    }
}
