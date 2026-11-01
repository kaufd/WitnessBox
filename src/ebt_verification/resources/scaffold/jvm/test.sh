#!/bin/bash
# test.sh заготовки ebt/ для Java/Kotlin на Gradle (ebt-gate --scaffold jvm).
#
# Договор гейта: рабочая папка — корень чистого клона; OUT_DIR — пустой абсолютный
# каталог результатов прогона. Аргументы — слова из EBT_TESTS; каждое становится
# отдельным фильтром Gradle --tests. Коды: 0 — тесты прошли, 1 — тесты выполнились
# и упали, 2 — ошибка исполнения. Свидетельства собираются в OUT_DIR при любом исходе.
#
# Настройки проекта — переменными окружения (значения по умолчанию — для JVM-модуля):
#   EBT_GRADLE_TASK     задача тестов; Android: :app:testDebugUnitTest
#   EBT_GRADLE_RESULTS  каталог XML-отчётов; Android: app/build/test-results/testDebugUnitTest
#   EBT_EVIDENCE_DIR    каталог JSONL от тестов; Android: app/build/ebt
#   EBT_TESTS           фильтры классов; по умолчанию *EbtTest
# Тесты пишут JSONL в build/ebt/<feature>.jsonl (см. docs/sdk.md); для Android это
# может быть app/build/ebt — тогда задайте EBT_EVIDENCE_DIR.
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: нужен OUT_DIR (запуск через ebt-gate)" >&2; exit 2; }

task=${EBT_GRADLE_TASK:-test}
results=${EBT_GRADLE_RESULTS:-build/test-results/test}
evidence_dir=${EBT_EVIDENCE_DIR:-build/ebt}

[ -x ./gradlew ] || { echo "test.sh: нет исполняемого ./gradlew в корне клона" >&2; exit 2; }

filters=("$@")
if [ ${#filters[@]} -eq 0 ]; then
  filters=('*EbtTest')
fi
gradle_args=()
for pattern in "${filters[@]}"; do
  gradle_args+=(--tests "$pattern")
done

# Свидетельства и отчёты прошлого прогона не должны пережить текущий.
rm -rf "$evidence_dir" "$results" || exit 2
log=$(mktemp) || exit 2
trap 'rm -f "$log"' EXIT

./gradlew -q "$task" "${gradle_args[@]}" --rerun 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}

# Свидетельства копируются при любом исходе: красный прогон тоже проверяется чекером.
mkdir -p "$OUT_DIR" || exit 2
shopt -s nullglob
evidence=("$evidence_dir"/*.jsonl)
if [ ${#evidence[@]} -gt 0 ]; then
  cp "${evidence[@]}" "$OUT_DIR"/ || exit 2
fi

[ "$rc" -eq 0 ] && exit 0
# Gradle возвращает 1 и на упавшие тесты, и на сломанную сборку. Код 1 — только если
# единственная причина отказа — «There were failing tests» и в свежих XML есть провалы;
# всё остальное, включая неоднозначный вывод, — 2 («проверки не было»).
#
# Проверка наличия XML обязательна: при nullglob без совпадений grep остался бы без
# имён файлов и читал stdin, то есть мог зависнуть вместо кода 2.
reports=("$results"/TEST-*.xml)
if [ ${#reports[@]} -eq 0 ]; then
  exit 2
fi
if grep -q "There were failing tests" "$log" && ! grep -q "Build completed with" "$log" \
   && grep -lqE '<testsuite [^>]*(failures="[1-9]|errors="[1-9])' "${reports[@]}" 2>/dev/null; then
  exit 1
fi
exit 2
