// SPDX-License-Identifier: MIT
// dart format off
// lib/ebt/ebt.dart
//
// EBT: recording proofs along the chain
// "requirement ⇒ invariant ⇒ proof".
//
// The file is pinned in pinned.txt byte for byte. Every statement takes one
// line shorter than 80 characters, so dart format of any style at width
// 80–120 leaves it alone; `dart format off` is a safeguard for tall style.
//
// Call ONLY inside assert. In release and profile builds assert is not
// executed: neither the call nor the argument evaluation happens. Whether
// the call code and data are removed from the binary has not been checked.
//
//   assert(ev('INV-CART-3', req: 'REQ-CART-1',
//       ok: result >= 0 && off <= subtotal,
//       data: {'subtotal': subtotal, 'off': off, 'result': result}));
//
// Valid data values (docs/sdk.md): null, bool, String, int, List and Map
// with string keys of those. Anything else (double, DateTime, enum, other
// objects) is an ArgumentError with the field path; the record is not logged.

import 'dart:collection';
import 'dart:convert';
import 'dart:developer' as developer;

/// Evidence fields: the `data` argument of [ev].
typedef EbtData = Map<String, Object?>;

/// Record a proof. Always returns true, so assert itself does not
/// fail; failing on a violation happens only in [Ebt.strict] mode.
bool ev(String inv, {required String req, required bool ok, EbtData? data}) {
  Ebt._record(inv, req, ok, data ?? const {});
  return true;
}

/// Invariant violation in strict mode.
class EbtViolation implements Exception {
  EbtViolation(this.record);
  final Map<String, Object?> record;
  @override
  String toString() => 'EBT violation: ${Ebt._encode(record)}';
}

class Ebt {
  Ebt._();

  // A record is stored as a JSON string taken at the ev() call: a later edit
  // of data or of a copy obtained from [records] does not change the proof.
  static final ListQueue<String> _records = ListQueue();
  static int _seq = 0;

  /// Current scope: a test name, screen or user flow.
  static String? scope;

  /// In tests: throw [EbtViolation] on an invariant violation.
  static bool strict = false;

  /// Duplicate records to DevTools → Logging (name EBT, violations EBT!).
  static bool toDevTools = true;

  /// Ring buffer so that long sessions do not eat memory.
  static int maxRecords = 50000;

  static void _record(String inv, String req, bool ok, EbtData data) {
    // Before ++_seq: a rejected record changes neither seq nor the log.
    _check(data, 'data');
    // No time or random values: the log is compared between runs.
    final rec = <String, Object?>{'seq': ++_seq};
    if (scope != null) rec['scope'] = scope;
    rec['req'] = req;
    rec['inv'] = inv;
    rec['ok'] = ok;
    rec['data'] = data;
    final line = _encode(rec);
    if (_records.length >= maxRecords) _records.removeFirst();
    _records.add(line);

    final name = ok ? 'EBT' : 'EBT!';
    final level = ok ? 800 : 1000;
    if (toDevTools) developer.log(line, name: name, level: level);
    if (strict && !ok) throw EbtViolation(_decode(line));
  }

  /// Copies of the records: changing them does not touch the log.
  static List<Map<String, Object?>> get records {
    final copies = _records.map(_decode);
    return List.unmodifiable(copies);
  }

  static List<Map<String, Object?>> get violations {
    final all = _records.map(_decode);
    return all.where((r) => r['ok'] == false).toList();
  }

  static void reset() {
    _records.clear();
    _seq = 0;
    scope = null;
  }

  /// Log in JSON Lines format, for diffs between runs and for an AI reviewer.
  static String toJsonl() => _records.join('\n');

  static String _encode(Object? o) => jsonEncode(o);

  static Map<String, Object?> _decode(String line) {
    final rec = jsonDecode(line);
    return rec as Map<String, Object?>;
  }

  // double is rejected even for a whole value: 1.0 is not an int on the VM.
  // On web int and double are one JS number, so 1.0 is int and is logged as 1.
  static void _check(Object? v, String path) {
    if (v == null || v is bool || v is String || v is int) return;
    if (v is List) {
      for (var i = 0; i < v.length; i++) {
        _check(v[i], '$path[$i]');
      }
      return;
    }
    if (v is Map) {
      for (final MapEntry(:key, :value) in v.entries) {
        if (key is! String) {
          throw ArgumentError('$path: key is not a string: $key');
        }
        _check(value, '$path.$key');
      }
      return;
    }
    final type = v.runtimeType;
    final what = 'cannot record value of type $type exactly';
    const hint = 'pass int, String, bool, List or Map';
    throw ArgumentError('$path: $what — $hint');
  }
}
