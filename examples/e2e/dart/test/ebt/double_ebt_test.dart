import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:witnessbox_e2e_dart/doubler.dart';
import 'package:witnessbox_e2e_dart/ebt/ebt.dart';

void main() {
  Ebt.toDevTools = false;

  // Evidence is written after all cases: partitions are zero/positive/negative.
  tearDownAll(() {
    Directory('build/ebt').createSync(recursive: true);
    File('build/ebt/double.jsonl').writeAsStringSync('${Ebt.toJsonl()}\n');
  });

  const cases = {'zero': 0, 'positive': 21, 'negative': -4};
  for (final MapEntry(key: name, :value) in cases.entries) {
    test(name, () {
      Ebt.scope = name;
      final result = doubleValue(value);
      assert(ev(
        'INV-EXAMPLE-1',
        req: 'REQ-EXAMPLE-1',
        ok: result == value * 2,
        data: {'value': value, 'result': result},
      ));
      expect(result, value * 2);
    });
  }
}
