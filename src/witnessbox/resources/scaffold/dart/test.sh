#!/bin/bash
# test.sh заготовки ebt/ для Dart/Flutter (ebt-gate --scaffold dart).
#
# Договор гейта: рабочая папка — корень чистого клона; OUT_DIR — пустой абсолютный
# каталог результатов прогона. Аргументы — слова из EBT_TESTS (фильтр тестов).
# Коды: 0 — тесты прошли, 1 — тесты выполнились и упали, 2 — ошибка исполнения.
# Свидетельства собираются в OUT_DIR/*.jsonl при любом исходе тестов.
#
# Тесты пишут JSONL в build/ebt/<feature>.jsonl (см. docs/sdk.md), поэтому скрипт
# копирует их в OUT_DIR. Если ваш test/ebt ещё не создан, гейт закончится ERROR
# «нет свидетельств» — это ожидаемое состояние заготовки, а не PASS.
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: нужен OUT_DIR (запуск через ebt-gate)" >&2; exit 2; }

command -v flutter >/dev/null 2>&1 || { echo "test.sh: не найден flutter; нужен Flutter SDK" >&2; exit 2; }

# Свидетельства прошлого прогона не должны пережить текущий, даже если тесты упали.
rm -rf build/ebt || exit 2

tests=("$@")
if [ ${#tests[@]} -eq 0 ]; then
  # По умолчанию — только тесты свидетельств: гейту не нужен весь набор, если EBT_TESTS не задан.
  tests=(test/ebt)
fi

# --no-pub: зависимости готовит prepare.sh проекта (flutter pub get), а не этот скрипт.
flutter test --no-pub "${tests[@]}"
rc=$?

mkdir -p "$OUT_DIR" || exit 2
shopt -s nullglob
evidence=(build/ebt/*.jsonl)
if [ ${#evidence[@]} -gt 0 ]; then
  cp "${evidence[@]}" "$OUT_DIR"/ || exit 2
fi

[ "$rc" -eq 0 ] && exit 0
# Flutter возвращает 1 и на упавшие тесты, и на часть ошибок сборки. Если проект
# различает их иначе, уточните здесь: 2 означает «проверки не было».
[ "$rc" -eq 1 ] && exit 1
exit 2
