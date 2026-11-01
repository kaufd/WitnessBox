// Тесты ebt.dart без package:test: `make test-dart` из корня проекта —
// golden читается по относительному пути. Запуск дважды: с --enable-asserts
// проверяется запись, без него — что ev() внутри assert не пишет.

import 'dart:io';

import '../../../src/witnessbox/resources/lib/ebt/ebt.dart';

void main() {
  var assertsOn = false;
  assert(assertsOn = true);
  Ebt.toDevTools = false;
  if (!assertsOn) {
    assert(ev('INV-N', req: 'REQ-N', ok: true));
    check(Ebt.toJsonl().isEmpty, 'без assert ev() записал: ${Ebt.toJsonl()}');
    print('ebt_test (без assert): OK');
    return;
  }
  goldenScenarioMatchesOtherSdks();
  unsupportedValueIsRejected();
  print('ebt_test: OK');
}

enum _Color { red }

/// Как unsupportedValueIsRejected в EbtTest.java: запись не попадает в лог и не сдвигает seq.
void unsupportedValueIsRejected() {
  Ebt.reset();
  final bad = <Object>[1.5, 1.0, DateTime(2026), _Color.red, Object(), {1: 'x'}];
  for (final value in bad) {
    try {
      assert(ev('INV-N', req: 'REQ-N', ok: true, data: {
        'v': [value],
      }));
      throw StateError('принято значение ${value.runtimeType}');
    } on ArgumentError catch (e) {
      check('$e'.contains('data.v[0]'), 'в ошибке нет пути поля: $e');
    }
  }
  check(Ebt.toJsonl().isEmpty, 'отклонённая запись попала в лог: ${Ebt.toJsonl()}');
  assert(ev('INV-N', req: 'REQ-N', ok: true, data: {
    'v': null,
    'big': 9223372036854775807,
  }));
  check(
      Ebt.toJsonl() ==
          '{"seq":1,"req":"REQ-N","inv":"INV-N","ok":true,'
              '"data":{"v":null,"big":9223372036854775807}}',
      'null и int вне безопасного диапазона JS должны записываться: ${Ebt.toJsonl()}');
}

/// Тот же сценарий, что в EbtTest.java и ebt.test.ts.
void goldenScenarioMatchesOtherSdks() {
  Ebt.reset();
  Ebt.scope = 'golden';
  assert(ev('INV-G', req: 'REQ-G', ok: true, data: {
    'int': -42,
    'max': 9007199254740991,
    'text': 'q"b\\s\nt\tr\rc\u0001 ё 😀',
    'flag': false,
    'none': null,
    'list': [1, null, [2, 'x'], {}],
    'map': {'b': 1, 'a': 2},
  }));
  assert(ev('INV-G', req: 'REQ-G', ok: false));
  Ebt.scope = null;
  assert(ev('INV-G', req: 'REQ-G', ok: true, data: {'n': 1}));
  final expected = File('tests/sdk/golden.jsonl').readAsStringSync();
  check('${Ebt.toJsonl()}\n' == expected,
      'golden расходится:\n${Ebt.toJsonl()}\n$expected');
}

void check(bool ok, String message) {
  if (!ok) throw StateError(message);
}
