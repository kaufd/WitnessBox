#!/bin/bash
# test.sh заготовки ebt/ для любого инструмента тестов (ebt-gate --scaffold generic).
#
# Договор гейта: рабочая папка — корень чистого клона; OUT_DIR — пустой абсолютный
# каталог результатов прогона. Аргументы — слова из EBT_TESTS; они передаются
# команде отдельными словами, без eval. Коды: 0 — тесты прошли, 1 — тесты
# выполнились и упали, 2 — ошибка исполнения. Свидетельства собираются в OUT_DIR
# при любом исходе тестов.
#
# Команда тестов задаётся переменной окружения:
#   EBT_TEST_CMD        обязательная строка команды; исполняется как
#                       bash -c "$EBT_TEST_CMD" "$@" — проект отвечает за кавычки,
#                       но подстановки из EBT_TESTS не исполняются как код;
#   EBT_EVIDENCE_DIR    каталог JSONL от тестов, по умолчанию build/ebt;
#   EBT_TEST_FAIL_CODES коды команды, означающие «тесты выполнились и упали»,
#                       через пробел, по умолчанию 1.
#
# Отображение кодов: 0 → 0; код из EBT_TEST_FAIL_CODES → 1; всё остальное → 2.
# Инструменты вроде Maven и Gradle возвращают 1 и на упавшие тесты, и на сломанную
# сборку: если это важно, разбирайте отчёты в своём test.sh или задайте точный
# набор кодов в EBT_TEST_FAIL_CODES (docs/scaffold.md).
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: нужен OUT_DIR (запуск через ebt-gate)" >&2; exit 2; }

[ -n "${EBT_TEST_CMD:-}" ] || {
  echo "test.sh: задайте EBT_TEST_CMD — команду тестов проекта (docs/scaffold.md, стек generic)" >&2
  exit 2
}

evidence_dir=${EBT_EVIDENCE_DIR:-build/ebt}
fail_codes=${EBT_TEST_FAIL_CODES:-1}

# Свидетельства прошлого прогона не должны пережить текущий, даже если тесты упали.
rm -rf "$evidence_dir" || exit 2

# Аргументы EBT_TESTS уходят команде отдельными словами: eval здесь не нужен и опасен.
bash -c "$EBT_TEST_CMD"' "$@"' _ "$@"
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
