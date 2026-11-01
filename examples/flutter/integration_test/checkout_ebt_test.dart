// integration_test/checkout_ebt_test.dart
//
// Пример сценария: UI-шаги прогоняют приложение, а логика под ними
// оставляет доказательства. В конце каждого теста лог уходит на хост.

import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:my_app/ebt/ebt.dart';
import 'package:my_app/main.dart' as app;

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  final dump = StringBuffer();

  setUp(Ebt.reset);

  tearDown(() {
    final chunk = Ebt.toJsonl();
    if (chunk.isNotEmpty) {
      if (dump.isNotEmpty) dump.writeln();
      dump.write(chunk);
    }
    // Обновляем после каждого теста — драйвер заберёт итог в конце.
    binding.reportData = {'ebt': dump.toString()};
  });

  testWidgets('checkout: скидка не уводит сумму в минус', (tester) async {
    Ebt.scope = 'checkout_discount';

    app.main();
    await tester.pumpAndSettle();

    // ... шаги сценария: добавить товар, применить промокод, перейти к оплате

    expect(
      Ebt.violations,
      isEmpty,
      reason: Ebt.violations.map((v) => v.toString()).join('\n'),
    );
  });
}
