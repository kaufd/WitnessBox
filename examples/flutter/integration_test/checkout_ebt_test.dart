// integration_test/checkout_ebt_test.dart
//
// Example scenario: the UI steps drive the application while the logic under them
// leaves proofs. At the end of each test the log goes to the host.

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
    // Updated after each test; the driver picks up the result at the end.
    binding.reportData = {'ebt': dump.toString()};
  });

  testWidgets('checkout: the discount does not push the total below zero', (tester) async {
    Ebt.scope = 'checkout_discount';

    app.main();
    await tester.pumpAndSettle();

    // ... scenario steps: add an item, apply a promo code, go to payment

    expect(
      Ebt.violations,
      isEmpty,
      reason: Ebt.violations.map((v) => v.toString()).join('\n'),
    );
  });
}
