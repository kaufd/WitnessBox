// SPDX-License-Identifier: MIT
// dart format off
// lib/ebt/ebt.dart
//
// EBT: запись доказательств по цепочке
// «требование ⇒ инвариант ⇒ доказательство».
//
// Файл закреплён в pinned.txt байт в байт. Каждый оператор занимает одну
// строку короче 80 символов, поэтому dart format любого стиля при ширине
// 80–120 его не меняет; `dart format off` — страховка для tall-стиля.
//
// Вызывать ТОЛЬКО внутри assert. В release и profile сборке assert не
// исполняется: ни вызов, ни вычисление аргументов не происходят. Удаляются ли
// код и данные вызова из бинарника, не проверялось.
//
//   assert(ev('INV-CART-3', req: 'REQ-CART-1',
//       ok: result >= 0 && off <= subtotal,
//       data: {'subtotal': subtotal, 'off': off, 'result': result}));
//
// Допустимые значения data — docs/sdk.md: null, bool, String, int, List и Map
// со строковыми ключами из них. Остальное (double, DateTime, enum, другие
// объекты) — ArgumentError с путём поля; запись в лог не попадает.

import 'dart:collection';
import 'dart:convert';
import 'dart:developer' as developer;

/// Поля свидетельства: аргумент `data` в [ev].
typedef EbtData = Map<String, Object?>;

/// Записать доказательство. Всегда возвращает true, поэтому assert сам
/// не падает; падение при нарушении — только в режиме [Ebt.strict].
bool ev(String inv, {required String req, required bool ok, EbtData? data}) {
  Ebt._record(inv, req, ok, data ?? const {});
  return true;
}

/// Нарушение инварианта в strict-режиме.
class EbtViolation implements Exception {
  EbtViolation(this.record);
  final Map<String, Object?> record;
  @override
  String toString() => 'EBT violation: ${Ebt._encode(record)}';
}

class Ebt {
  Ebt._();

  // Запись хранится строкой JSON, снятой в момент ev(): поздняя правка data
  // или полученной из [records] копии не меняет доказательство.
  static final ListQueue<String> _records = ListQueue();
  static int _seq = 0;

  /// Текущий сценарий: имя теста, экран или user flow.
  static String? scope;

  /// В тестах: бросать [EbtViolation] при нарушении инварианта.
  static bool strict = false;

  /// Дублировать записи в DevTools → Logging (имя EBT, нарушения — EBT!).
  static bool toDevTools = true;

  /// Кольцевой буфер, чтобы долгие сессии не съели память.
  static int maxRecords = 50000;

  static void _record(String inv, String req, bool ok, EbtData data) {
    // До ++_seq: отклонённая запись не меняет ни seq, ни лог.
    _check(data, 'data');
    // Без времени и случайных значений: лог сравнивается между прогонами.
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

  /// Копии записей: их изменение не трогает лог.
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

  /// Лог в формате JSON Lines — для диффа между прогонами и для ИИ-ревьюера.
  static String toJsonl() => _records.join('\n');

  static String _encode(Object? o) => jsonEncode(o);

  static Map<String, Object?> _decode(String line) {
    final rec = jsonDecode(line);
    return rec as Map<String, Object?>;
  }

  // double отклоняется и при целом значении: 1.0 на VM не int. На web int и
  // double — одно JS-число, там 1.0 is int и запишется как 1.
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
          throw ArgumentError('$path: ключ не строка: $key');
        }
        _check(value, '$path.$key');
      }
      return;
    }
    final type = v.runtimeType;
    final what = 'нельзя записать точно значение типа $type';
    const hint = 'передайте int, String, bool, List или Map';
    throw ArgumentError('$path: $what — $hint');
  }
}
