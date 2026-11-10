// SPDX-License-Identifier: MIT
package ebt;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;

/**
 * EBT evidence recording on the JVM (Java and Kotlin): JSONL lines in the same format as ebt.ts:
 * {"seq","scope"?,"req","inv","ok","data"}. It makes no decisions: the checker verifies the rule.
 *
 * No dependencies; only APIs present in both JDK 17 and android.jar (API 26+).
 * A record is serialized at the ev() call, so it is a snapshot: changing the passed collections
 * after the call does not affect the log. A value that cannot be recorded
 * exactly (fractional numbers, BigDecimal, an arbitrary object) causes an IllegalArgumentException,
 * not a string: evidence must not silently lose precision.
 *
 * Enabling is not controlled: the file goes only into the test source set (src/test/java),
 * and does not get into the application build. Methods are synchronized: tests may write from coroutines.
 */
public final class Ebt {

    private static final List<String> records = new ArrayList<>();
    private static int seq = 0;
    private static String scope = null;

    private Ebt() {
    }

    public static synchronized void ev(String inv, String req, boolean ok, Map<String, ?> data) {
        StringBuilder out = new StringBuilder();
        out.append("{\"seq\":").append(seq + 1);
        if (scope != null) {
            out.append(",\"scope\":");
            string(out, scope);
        }
        out.append(",\"req\":");
        string(out, req);
        out.append(",\"inv\":");
        string(out, inv);
        out.append(",\"ok\":").append(ok).append(",\"data\":");
        value(out, data, "data");
        out.append('}');
        seq++;
        records.add(out.toString());
    }

    public static synchronized void setScope(String value) {
        scope = value;
    }

    public static synchronized String toJsonl() {
        return String.join("\n", records);
    }

    public static synchronized void reset() {
        records.clear();
        seq = 0;
        scope = null;
    }

    public static synchronized void writeTo(Path file) throws IOException {
        Path parent = file.toAbsolutePath().getParent();
        if (parent != null) Files.createDirectories(parent);
        // Files.write(Path, byte[]), not writeString: Android unit tests compile against
        // android.jar, which has no writeString; write exists since API 26.
        Files.write(file, toJsonl().getBytes(StandardCharsets.UTF_8));
    }

    private static void value(StringBuilder out, Object v, String path) {
        if (v == null) {
            out.append("null");
        } else if (v instanceof String s) {
            string(out, s);
        } else if (v instanceof Boolean b) {
            out.append(b);
        } else if (v instanceof Integer || v instanceof Long || v instanceof Short || v instanceof Byte) {
            out.append(v);
        } else if (v instanceof Map<?, ?> map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : map.entrySet()) {
                if (!(e.getKey() instanceof String key)) {
                    throw new IllegalArgumentException(path + ": key is not a string: " + e.getKey());
                }
                if (!first) out.append(',');
                first = false;
                string(out, key);
                out.append(':');
                value(out, e.getValue(), path + "." + key);
            }
            out.append('}');
        } else if (v instanceof Collection<?> list) {
            out.append('[');
            int i = 0;
            for (Object item : list) {
                if (i > 0) out.append(',');
                value(out, item, path + "[" + i + "]");
                i++;
            }
            out.append(']');
        } else {
            throw new IllegalArgumentException(path + ": cannot record a value of type "
                    + v.getClass().getName() + " exactly; pass an integer, string, bool, list or map");
        }
    }

    private static void string(StringBuilder out, String s) {
        out.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) out.append(String.format("\\u%04x", (int) c));
                    else out.append(c);
                }
            }
        }
        out.append('"');
    }
}
