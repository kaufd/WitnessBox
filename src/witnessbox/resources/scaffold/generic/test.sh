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
#   EBT_TEST_CMD        обязательная строка команды; исполняется как bash -c.
#                       Слова EBT_TESTS добавляются к последней команде, если сама
#                       команда не ссылается на "$@"/"$*": тогда они приходят ей
#                       позиционными параметрами. Хвостовые переводы строк и
#                       комментарий в конце строки отбрасываются — иначе аргументы
#                       потерялись бы или выполнились отдельной командой;
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

# Готовим команду, не исполняя аргументы как код: хвостовой комментарий и переводы
# строк отбрасываются; если команда сама ссылается на "$@", аргументы не дублируются.
prepared_cmd=
command_uses_args=0

trim_command() {
  local value=$1
  while [ -n "$value" ]; do
    case ${value:${#value}-1:1} in
      ' '|$'\t'|$'\n'|$'\r') value=${value%?} ;;
      *) break ;;
    esac
  done
  printf '%s' "$value"
}

prepare_command() {
  local cmd i c prev next quote=0 escaped=0 in_comment=0 comment=-1 newline=-1
  cmd=$(trim_command "$1")
  for ((i = 0; i < ${#cmd}; i++)); do
    c=${cmd:i:1}
    if [ "$in_comment" = 1 ]; then
      [ "$c" = $'\n' ] && { in_comment=0; newline=$i; }
      continue
    fi
    if [ "$escaped" = 1 ]; then escaped=0; continue; fi
    if [ "$quote" = 1 ]; then
      [ "$c" = "'" ] && quote=0
      continue
    fi
    if [ "$quote" = 2 ]; then
      case $c in
        '\') escaped=1 ;;
        '"') quote=0 ;;
        '$')
          next=${cmd:i+1:1}
          case $next in
            '@'|'*') command_uses_args=1 ;;
            '{') case ${cmd:i+1:2} in '{@'|'{*') command_uses_args=1 ;; esac ;;
          esac ;;
      esac
      continue
    fi
    case $c in
      '\') escaped=1 ;;
      "'") quote=1 ;;
      '"') quote=2 ;;
      $'\n') newline=$i ;;
      '$')
        next=${cmd:i+1:1}
        case $next in
          '@'|'*') command_uses_args=1 ;;
          '{') case ${cmd:i+1:2} in '{@'|'{*') command_uses_args=1 ;; esac ;;
        esac ;;
      '#')
        if [ "$i" -eq 0 ]; then
          comment=$i
          in_comment=1
        else
          prev=${cmd:i-1:1}
          case $prev in ' '|$'\t'|$'\n'|';'|'&'|'|'|'(')
            comment=$i
            in_comment=1 ;;
          esac
        fi ;;
    esac
  done
  if [ "$comment" -ge 0 ] && [ "$comment" -gt "$newline" ]; then
    cmd=$(trim_command "${cmd:0:$comment}")
  fi
  prepared_cmd=$cmd
}

prepare_command "$EBT_TEST_CMD"
[ -n "$prepared_cmd" ] || {
  echo "test.sh: EBT_TEST_CMD пуст после удаления комментария" >&2
  exit 2
}

if [ "$command_uses_args" = 1 ]; then
  # Команда сама раскрывает "$@": аргументы передаются ей как позиционные параметры.
  bash -c "$prepared_cmd" _ "$@"
else
  # Слова EBT_TESTS — отдельные argv последней команды, без eval и повторного разбора.
  bash -c "$prepared_cmd"' "$@"' _ "$@"
fi
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
