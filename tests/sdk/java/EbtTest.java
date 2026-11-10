package ebt;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Tests of Ebt.java without JUnit: `make test-java` (javac + java -ea). Run from the project root:
 * the format fixture is read by a relative path.
 */
public final class EbtTest {

    private static final Path FIXTURE = Path.of("src/witnessbox/checker/fixtures/record.jsonl");
    private static final Path GOLDEN = Path.of("tests/sdk/golden.jsonl");

    public static void main(String[] args) throws Exception {
        boolean assertsOn = false;
        assert assertsOn = true;
        if (!assertsOn) throw new AssertionError("run with -ea");

        recordMatchesFormatFixture();
        goldenScenarioMatchesOtherSdks();
        recordIsSnapshotAtCallTime();
        unsupportedValueIsRejected();
        stringsAreEscaped();
        noScopeMeansNoScopeField();
        resetRestartsSeq();
        writeToCreatesFolderAndWritesJsonl();
        System.out.println("EbtTest: OK");
    }

    private static Map<String, Object> cart() {
        Map<String, Object> discount = new LinkedHashMap<>();
        discount.put("type", "none");
        discount.put("value", 0);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("lines", List.of(List.of(49900, 1), List.of(1990, 3)));
        data.put("discount", discount);
        data.put("subtotal", 55870);
        data.put("off", 0);
        data.put("result", 55870L);
        return data;
    }

    static void recordMatchesFormatFixture() throws Exception {
        Ebt.reset();
        Ebt.setScope("fixture");
        Ebt.ev("INV-CART-3", "REQ-CART-1", true, cart());
        String expected = Files.readString(FIXTURE, StandardCharsets.UTF_8);
        check(Ebt.toJsonl().equals(expected), "format differs from the fixture:\n" + Ebt.toJsonl() + "\n" + expected);
    }

    /** The same scenario as in ebt.test.ts and ebt_test.dart; field order is set by LinkedHashMap only for byte comparison. */
    static void goldenScenarioMatchesOtherSdks() throws Exception {
        Ebt.reset();
        Ebt.setScope("golden");
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("b", 1);
        map.put("a", 2);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("int", -42);
        data.put("max", 9007199254740991L);
        data.put("text", "q\"b\\s\nt\tr\rc\u0001 ё 😀");
        data.put("flag", false);
        data.put("none", null);
        data.put("list", Arrays.asList(1, null, List.of(2, "x"), Map.of()));
        data.put("map", map);
        Ebt.ev("INV-G", "REQ-G", true, data);
        Ebt.ev("INV-G", "REQ-G", false, Map.of());
        Ebt.setScope(null);
        Ebt.ev("INV-G", "REQ-G", true, Map.of("n", 1));
        String expected = Files.readString(GOLDEN, StandardCharsets.UTF_8);
        check((Ebt.toJsonl() + "\n").equals(expected), "golden differs:\n" + Ebt.toJsonl() + "\n" + expected);
    }

    static void recordIsSnapshotAtCallTime() {
        Ebt.reset();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("n", 1);
        Ebt.ev("INV-N", "REQ-N", true, data);
        data.put("n", 2);
        check(Ebt.toJsonl().equals("{\"seq\":1,\"req\":\"REQ-N\",\"inv\":\"INV-N\",\"ok\":true,\"data\":{\"n\":1}}"),
                "the record changed after ev: " + Ebt.toJsonl());
    }

    static void unsupportedValueIsRejected() {
        Ebt.reset();
        for (Object bad : List.of(1.5, 1.5f, new java.math.BigDecimal("1.5"), 'x', new Object())) {
            try {
                Ebt.ev("INV-N", "REQ-N", true, Map.of("v", List.of(bad)));
                throw new AssertionError("value accepted: " + bad.getClass().getSimpleName());
            } catch (IllegalArgumentException e) {
                check(e.getMessage().contains("v[0]"), "the error has no field path: " + e.getMessage());
            }
        }
        check(Ebt.toJsonl().isEmpty(), "a rejected record reached the log: " + Ebt.toJsonl());
        Map<String, Object> legal = new LinkedHashMap<>();
        legal.put("v", null);
        legal.put("big", Long.MAX_VALUE);
        Ebt.ev("INV-N", "REQ-N", true, legal);
        check(Ebt.toJsonl().equals("{\"seq\":1,\"req\":\"REQ-N\",\"inv\":\"INV-N\",\"ok\":true,"
                + "\"data\":{\"v\":null,\"big\":9223372036854775807}}"),
                "null and long outside the JS safe range must be recorded: " + Ebt.toJsonl());
    }

    static void stringsAreEscaped() {
        Ebt.reset();
        Ebt.ev("INV-N", "REQ-N", false, Map.of("s", "a\"b\\c\nd\u0001ё"));
        String expected = "{\"seq\":1,\"req\":\"REQ-N\",\"inv\":\"INV-N\",\"ok\":false,"
                + "\"data\":{\"s\":\"a\\\"b\\\\c\\nd\\u0001ё\"}}";
        check(Ebt.toJsonl().equals(expected), "escaping: " + Ebt.toJsonl());
    }

    static void noScopeMeansNoScopeField() {
        Ebt.reset();
        Ebt.setScope("x");
        Ebt.setScope(null);
        Ebt.ev("INV-N", "REQ-N", true, Map.of());
        check(!Ebt.toJsonl().contains("scope"), "scope field without scope: " + Ebt.toJsonl());
    }

    static void resetRestartsSeq() {
        Ebt.reset();
        Ebt.setScope("x");
        Ebt.ev("INV-N", "REQ-N", true, Map.of());
        Ebt.ev("INV-N", "REQ-N", true, Map.of());
        check(Ebt.toJsonl().contains("\"seq\":2"), "seq does not grow: " + Ebt.toJsonl());
        Ebt.reset();
        Ebt.ev("INV-N", "REQ-N", true, Map.of());
        check(Ebt.toJsonl().equals("{\"seq\":1,\"req\":\"REQ-N\",\"inv\":\"INV-N\",\"ok\":true,\"data\":{}}"),
                "reset did not clear seq or scope: " + Ebt.toJsonl());
    }

    static void writeToCreatesFolderAndWritesJsonl() throws Exception {
        Ebt.reset();
        Ebt.ev("INV-N", "REQ-N", true, Map.of("s", "ё"));
        Path dir = Files.createTempDirectory("ebt");
        Path file = dir.resolve("a/b/e.jsonl");
        Ebt.writeTo(file);
        check(Files.readString(file, StandardCharsets.UTF_8).equals(Ebt.toJsonl()), "writeTo writes the wrong thing");
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
}
