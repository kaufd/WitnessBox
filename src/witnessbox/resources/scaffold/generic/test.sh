#!/bin/bash
# test.sh заготовки ebt/ для любого инструмента тестов (witnessbox scaffold generic).
#
# Договор гейта: рабочая папка — корень чистого клона; OUT_DIR — пустой абсолютный
# каталог результатов прогона. Аргументы — слова из EBT_TESTS; они передаются
# команде отдельными словами, без eval. Коды: 0 — тесты прошли, 1 — тесты
# выполнились и упали, 2 — ошибка исполнения. Свидетельства собираются в OUT_DIR
# при любом исходе тестов.
#
# Команда тестов задаётся переменной окружения:
#   EBT_TEST_CMD        обязательная простая команда; исполняется как bash -c, слова
#                       EBT_TESTS дописываются в её конец отдельными argv. Сложный
#                       сценарий (несколько команд, конвейер) — свой скрипт;
#   EBT_EVIDENCE_DIR    каталог JSONL от тестов, по умолчанию build/ebt;
#   EBT_TEST_FAIL_CODES коды команды, означающие «тесты выполнились и упали»,
#                       через пробел, по умолчанию 1.
#
# Отображение кодов: 0 → 0; код из EBT_TEST_FAIL_CODES → 1; всё остальное → 2.
# Инструменты вроде Maven и Gradle возвращают 1 и на упавшие тесты, и на сломанную
# сборку: если это важно, разбирайте отчёты в своём test.sh или задайте точный
# набор кодов в EBT_TEST_FAIL_CODES (docs/scaffold.md).
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: нужен OUT_DIR (запуск через witnessbox gate)" >&2; exit 2; }

[ -n "${EBT_TEST_CMD:-}" ] || {
  echo "test.sh: задайте EBT_TEST_CMD — команду тестов проекта (docs/scaffold.md, стек generic)" >&2
  exit 2
}

evidence_dir=${EBT_EVIDENCE_DIR:-build/ebt}
fail_codes=${EBT_TEST_FAIL_CODES:-1}

# Свидетельства прошлого прогона не должны пережить текущий, даже если тесты упали.
rm -rf "$evidence_dir" || exit 2

# Хвостовой перевод строки (блок `|` в YAML) превратил бы дописанные аргументы
# в отдельную команду.
cmd=${EBT_TEST_CMD%"${EBT_TEST_CMD##*[![:space:]]}"}
[ -n "$cmd" ] || { echo "test.sh: EBT_TEST_CMD пуст" >&2; exit 2; }

# Слова EBT_TESTS — отдельные argv в конце команды, без eval и повторного разбора.
bash -c "$cmd"' "$@"' _ "$@"
rc=$?

# Свидетельства копируются при любом исходе: красный прогон тоже проверяется чекером.
mkdir -p "$OUT_DIR" || exit 2
shopt -s nullglob
evidence=("$evidence_dir"/*.jsonl)
if [ ${#evidence[@]} -gt 0 ]; then
  cp "${evidence[@]}" "$OUT_DIR"/ || exit 2
fi

[ "$rc" -eq 0 ] && exit 0
for code in $fail_codes; do
  [ "$rc" = "$code" ] && exit 1
done
exit 2
