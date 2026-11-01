// test_driver/integration_test.dart
//
// Забирает лог доказательств с устройства/эмулятора и кладёт его в файл.
// Запуск:
//   flutter drive \
//     --driver=test_driver/integration_test.dart \
//     --target=integration_test/checkout_ebt_test.dart

import 'dart:io';

import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver(
      responseDataCallback: (data) async {
        final jsonl = (data?['ebt'] as String?) ?? '';
        final file = File('build/ebt/evidence.jsonl');
        await file.create(recursive: true);
        await file.writeAsString(jsonl);
      },
    );
