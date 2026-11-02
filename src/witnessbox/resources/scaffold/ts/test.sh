#!/bin/bash
# test.sh заготовки ebt/ для TypeScript/Vite/Vitest (witnessbox scaffold ts).
#
# Договор гейта: рабочая папка — корень чистого клона; OUT_DIR — пустой абсолютный
# каталог результатов прогона. Аргументы — слова из EBT_TESTS (фильтр vitest).
# Коды: 0 — тесты прошли, 1 — тесты выполнились и упали, 2 — ошибка исполнения.
# Свидетельства собираются в OUT_DIR/*.jsonl при любом исходе тестов.
#
# Тесты пишут JSONL в build/ebt/<feature>.jsonl (см. docs/sdk.md), поэтому скрипт
# копирует их в OUT_DIR. Зависимости готовит prepare.sh (bun install), а не этот
# скрипт; без node_modules vitest упадёт, и код вернётся ниже.
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: нужен OUT_DIR (запуск через witnessbox gate)" >&2; exit 2; }

command -v bunx >/dev/null 2>&1 || { echo "test.sh: не найден bunx; нужен Bun" >&2; exit 2; }

# Свидетельства прошлого прогона не должны пережить текущий, даже если тесты упали.
rm -rf build/ebt || exit 2

tests=("$@")
if [ ${#tests[@]} -eq 0 ]; then
  # По умолчанию — только тесты свидетельств (*.ebt.test.ts): остальной набор гейту не нужен.
  tests=(.ebt.test)
fi

bunx vitest run "${tests[@]}"
rc=$?

mkdir -p "$OUT_DIR" || exit 2
shopt -s nullglob
evidence=(build/ebt/*.jsonl)
if [ ${#evidence[@]} -gt 0 ]; then
  cp "${evidence[@]}" "$OUT_DIR"/ || exit 2
fi

[ "$rc" -eq 0 ] && exit 0
# Vitest возвращает 1 и на упавшие тесты, и на часть ошибок загрузки конфигурации.
# Если проект различает их иначе, уточните здесь: 2 означает «проверки не было».
[ "$rc" -eq 1 ] && exit 1
exit 2
