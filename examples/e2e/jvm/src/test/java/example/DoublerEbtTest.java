package example;

import ebt.Ebt;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** Три класса входов шаблонной spec: zero, positive, negative. */
final class DoublerEbtTest {

    @AfterAll
    static void writeEvidence() throws IOException {
        Ebt.writeTo(Path.of("build/ebt/double.jsonl"));
    }

    private static void check(String scope, int value) {
        Ebt.setScope(scope);
        int result = Doubler.twice(value);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("value", value);
        data.put("result", result);
        Ebt.ev("INV-EXAMPLE-1", "REQ-EXAMPLE-1", result == value * 2, data);
        assertEquals(value * 2, result, scope);
    }

    @Test
    void zero() {
        check("zero", 0);
    }

    @Test
    void positive() {
        check("positive", 21);
    }

    @Test
    void negative() {
        check("negative", -4);
    }
}
