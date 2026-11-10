// Tests of ebt.dart without package:test: `make test-dart` from the project root;
// golden is read by a relative path. Run twice: with --enable-asserts
// recording is checked, without it that ev() inside assert does not record.

import 'dart:io';

import '../../../src/witnessbox/resources/lib/ebt/ebt.dart';

void main() {
  var assertsOn = false;
  assert(assertsOn = true);
  Ebt.toDevTools = false;
  if (!assertsOn) {
    assert(ev('INV-N', req: 'REQ-N', ok: true));
    check(Ebt.toJsonl().isEmpty, 'without assert ev() recorded: ${Ebt.toJsonl()}');
    print('ebt_test (without assert): OK');
    return;
  }
  goldenScenarioMatchesOtherSdks();
  unsupportedValueIsRejected();
  print('ebt_test: OK');
}

enum _Color { red }

/// As unsupportedValueIsRejected in EbtTest.java: the record does not reach the log and does not shift seq.
void unsupportedValueIsRejected() {
  Ebt.reset();
  final bad = <Object>[1.5, 1.0, DateTime(2026), _Color.red, Object(), {1: 'x'}];
  for (final value in bad) {
    try {
      assert(ev('INV-N', req: 'REQ-N', ok: true, data: {
        'v': [value],
      }));
      throw StateError('value accepted: ${value.runtimeType}');
    } on ArgumentError catch (e) {
      check('$e'.contains('data.v[0]'), 'the error has no field path: $e');
    }
  }
  check(Ebt.toJsonl().isEmpty, 'a rejected record reached the log: ${Ebt.toJsonl()}');
  assert(ev('INV-N', req: 'REQ-N', ok: true, data: {
    'v': null,
    'big': 9223372036854775807,
  }));
  check(
      Ebt.toJsonl() ==
          '{"seq":1,"req":"REQ-N","inv":"INV-N","ok":true,'
              '"data":{"v":null,"big":9223372036854775807}}',
      'null and int outside the JS safe range must be recorded: ${Ebt.toJsonl()}');
}

/// The same scenario as in EbtTest.java and ebt.test.ts.
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
      'golden differs:\n${Ebt.toJsonl()}\n$expected');
}

void check(bool ok, String message) {
  if (!ok) throw StateError(message);
}
