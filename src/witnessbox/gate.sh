#!/bin/bash
# witnessbox gate <ebt-dir> <clone> <run-dir>; публичный вход — cli.py этой поставки.
# test.sh получает пустой абсолютный OUT_DIR; прежние build/ebt/*.jsonl — через мост.
# Коды: 0 PASS, 1 FAIL, 2 ERROR; тот же итог — в <run-dir>/gate.json (формат 1).
# BASE, EBT_TESTS, EBT_INV, EBT_CHECK сохранены.
set -uo pipefail

[ $# -eq 3 ] || { echo "usage: witnessbox gate <ebt-dir> <clone> <run-dir>" >&2; exit 2; }
mkdir -p "$3" && run=$(cd "$3" && pwd) || exit 2
# Итог прошлой попытки в той же папке не должен пережить ранний выход этой.
out="$run/out"
rm -rf "$out" "$run/inputs" && rm -f "$run"/{gate.md,gate.json,report.md,report.json,evidence.jsonl,test.log,prepare.log,ebt-check.err,installation.json} \
  || { echo "не удалось очистить итоги прошлой попытки в $run" >&2; exit 2; }
py=${EBT_VERIFICATION_PYTHON:-}
[ -n "$py" ] || { echo "запускайте установленную команду witnessbox gate" >&2; exit 2; }

# gate.json пишется при любом итоге, как только известен каталог результатов.
summary() {
  "$py" -I -c 'import sys; from witnessbox.cli import write_summary; write_summary(*sys.argv[1:])' \
    "$run" "$1" "$2" "${3:-}" "${head:-}" "${test_rc:-}" "${check_rc:-}" \
    "${checker_command:-}" "${checker_hash:-}" "${spec_file:-}"
}
# Стадии имеют общий контекст одного запуска; любой отказ инфраструктуры — ERROR.
fail() {
  error_message="$*"
  echo "$*" >&2
  summary 2 gate_error "$*" || rm -f "$run/gate.json"
  exit 2
}

ebt=$(cd "$1" && pwd) || fail "нет каталога проверки $1"
spec_file="$ebt/spec.toml"
clone=$(cd "$2" && pwd) || fail "нет клона $2"
tests=${EBT_TESTS:-}
package=$(cd "$(dirname "$0")" && pwd) || fail "не найден каталог поставки"
kit="$package/resources"
check="$package/checker/ebt_check.py"
[ -f "$ebt/spec.toml" ] || fail "нет $ebt/spec.toml"

installation=$("$py" -I -m witnessbox.cli --installation) || fail "не удалось определить установку"
printf '%s\n' "$installation" > "$run/installation.json" || fail "не удалось записать installation.json"
supply_name=$("$py" -I -c 'from witnessbox.cli import installation; i=installation(); print(i["distribution"], i["version"], "в", i["package"], "; gate sha256", i["gate_sha256"])') \
  || fail "не удалось определить поставку"
if [ -n "${EBT_CHECK:-}" ]; then
  checker_path=$(command -v "$EBT_CHECK") || fail "EBT_CHECK=$EBT_CHECK: команда не найдена"
  case $checker_path in /*) ;; *) checker_path="$PWD/$checker_path" ;; esac
  [ -x "$checker_path" ] || fail "EBT_CHECK=$EBT_CHECK: не исполняемый файл $checker_path"
  checker=("$checker_path")
  checker_command=$checker_path
  version=$("${checker[@]}" --version 2>&1) || fail "EBT_CHECK=$EBT_CHECK: --version упал"
  checker_hash=$(shasum -a 256 "$checker_path") || fail "не удалось хэшировать $checker_path"
  checker_hash=${checker_hash%% *}
  checker_name="EBT_CHECK=$EBT_CHECK ($checker_path), $version; sha256 $checker_hash"
else
  checker=("$py" -I -m witnessbox.checker.ebt_check)
  checker_command=$check
  version=$("${checker[@]}" --version) || fail "witnessbox check --version упал"
  checker_hash=$("$py" -I -c 'from witnessbox.cli import installation; print(installation()["checker_sha256"])') \
    || fail "не удалось определить sha256 чекера"
  checker_name="$version; $check; sha256 $checker_hash"
fi

select_runner() {
  case ${EBT_RUNNER:-} in
    ''|test.sh|flutter) ;;
    *) fail "EBT_RUNNER=$EBT_RUNNER: неизвестный runner (test.sh или flutter)" ;;
  esac
  if [ -e "$ebt/test.sh" ] || [ -L "$ebt/test.sh" ]; then
    [ -f "$ebt/test.sh" ] && [ -x "$ebt/test.sh" ] || fail "test.sh существует, но не является исполняемым файлом: $ebt/test.sh"
    [ "${EBT_RUNNER:-}" != flutter ] || fail "EBT_RUNNER=flutter: пакет содержит test.sh; используйте EBT_RUNNER=test.sh"
    runner_kind=test.sh
    runner="test.sh${tests:+ $tests}"
    runner_command=("$ebt/test.sh")
  else
    [ "${EBT_RUNNER:-}" != test.sh ] || fail "нет $ebt/test.sh: добавьте исполняемый test.sh или выберите EBT_RUNNER=flutter"
    if [ -z "${EBT_RUNNER:-}" ]; then
      echo "Совместимость: без test.sh выбран legacy Flutter adapter; добавьте test.sh или задайте EBT_RUNNER=flutter явно" >&2
    fi
    # Конкретная команда и сведения о Flutter принадлежат только legacy adapter.
    source "$package/runners/flutter.sh" || fail "не удалось загрузить legacy Flutter adapter"
    select_legacy_flutter
  fi
}

preflight_git() {
  cd "$clone" || fail "не удалось открыть клон $clone"
  # До status: в репозитории без коммитов все файлы неотслеживаемые, и «грязное дерево» скрыло бы причину.
  if ! head=$(git rev-parse -q --verify HEAD); then
    git rev-parse --git-dir >/dev/null 2>&1 && fail "в репозитории нет коммитов — гейт проверяет только закоммиченное"
    fail "git rev-parse HEAD упал"
  fi
  status=$(git status --porcelain) || fail "git status упал: чистота клона не проверена"
  if [ -n "$status" ]; then
    echo "$status" >&2
    fail "дерево клона не чистое — гейт проверяет только закоммиченное"
  fi
  # Не прятать отказ git за успешным grep или пустой подстановкой.
  tracked=$(git ls-files -v) || fail "git ls-files упал: скрытые правки не проверены"
  hidden=$(printf '%s\n' "$tracked" | sed -n '/^[a-zS] /p') || fail "не удалось проверить пометки git"
  if [ -n "$hidden" ]; then
    echo "$hidden" >&2
    fail "в клоне есть skip-worktree/assume-unchanged — тесты могут идти по незакоммиченному коду"
  fi
  protected=""
  if [ -n "${BASE:-}" ]; then
    git rev-parse -q --verify "$BASE^{commit}" >/dev/null || fail "BASE=$BASE: такого коммита нет"
    protected=$(git diff --name-only "$BASE" HEAD -- ebt tool/ebt_check) || fail "git diff от BASE упал"
  fi
  drifted=""
  if [ -f "$ebt/pinned.txt" ]; then
    while read -r src dest _ || [ -n "$src" ]; do
      case $src in ''|'#'*) continue ;; kit:*) src="$kit/${src#kit:}" ;; /*) ;; *) src="$ebt/$src" ;; esac
      [ -f "$src" ] || fail "pinned.txt: нет оригинала $src"
      cmp -s "$src" "$dest"
      cmp_rc=$?
      case $cmp_rc in
        0) ;;
        1) drifted="$drifted $dest" ;;
        *) [ -e "$dest" ] && fail "pinned.txt: не удалось сравнить $src и $dest"
           drifted="$drifted $dest" ;;
      esac
    done < "$ebt/pinned.txt" || fail "не удалось прочитать pinned.txt"
  fi
}

stash_changes() {
  git -C "$clone" stash push -q -m "witnessbox gate: изменения за прогон $head" >/dev/null 2>&1
}
cleanup_exit() {
  exit_rc=$?
  trap - EXIT
  if ! stash_changes; then
    rm -f "$run/gate.md"
    echo "не удалось сохранить изменения прогона в git stash" >&2
    summary 2 gate_error "${error_message:+$error_message; }не удалось сохранить изменения прогона в git stash" \
      || rm -f "$run/gate.json"
    exit_rc=2
  fi
  exit "$exit_rc"
}

# Код проекта (prepare.sh, test.sh) исполняется с правами гейта: чекер читает копию входов,
# снятую до него, а правка оригиналов или поставки за прогон — ошибка. Это обнаружение, не песочница.
inputs_list="spec.toml checks.py known.toml baseline.jsonl"
snapshot_inputs() {
  inputs="$run/inputs"
  mkdir "$inputs" || fail "не удалось создать $inputs"
  for name in $inputs_list; do
    [ -f "$ebt/$name" ] || continue
    cp "$ebt/$name" "$inputs/$name" || fail "не удалось скопировать $ebt/$name в $inputs"
  done
  spec_file="$inputs/spec.toml"
}

verify_inputs() {
  changed=""
  for name in $inputs_list; do
    if [ -f "$inputs/$name" ]; then
      cmp -s "$inputs/$name" "$ebt/$name" || changed="$changed $name"
    elif [ -e "$ebt/$name" ] || [ -L "$ebt/$name" ]; then
      changed="$changed $name"
    fi
  done
  [ -z "$changed" ] || fail "входы проверки в $ebt изменены во время прогона:$changed"
  now=$("$py" -I -m witnessbox.cli --installation) || fail "не удалось повторно определить установку"
  [ "$now" = "$installation" ] || fail "код поставки изменён во время прогона, см. $run/installation.json"
  if [ -n "${EBT_CHECK:-}" ]; then
    now=$(shasum -a 256 "$checker_path") || fail "не удалось повторно хэшировать $checker_path"
    [ "${now%% *}" = "$checker_hash" ] || fail "EBT_CHECK=$EBT_CHECK: чекер изменён во время прогона"
  fi
}

run_tests() {
  if [ -x "$ebt/prepare.sh" ]; then
    exec 3> "$run/prepare.log" || fail "не удалось открыть prepare.log"
    "$ebt/prepare.sh" >&3 2>&1
    prepare_rc=$?
    exec 3>&-
    [ $prepare_rc -eq 0 ] || fail "prepare.sh упал, см. $run/prepare.log"
  fi
  rm -f build/ebt/*.jsonl || fail "не удалось удалить свидетельства прошлого запуска в build/ebt/"
  mkdir -p "$out" || fail "не удалось создать $out"
  exec 3> "$run/test.log" || fail "не удалось открыть test.log"
  OUT_DIR="$out" "${runner_command[@]}" $tests >&3 2>&1
  test_rc=$?
  exec 3>&-
  runner_error=""
  [ $test_rc -gt 1 ] && runner_error=1
  current_head=$(git rev-parse --verify HEAD) || fail "git rev-parse HEAD после тестов упал"
  [ "$current_head" = "$head" ] || fail "HEAD клона сменился во время прогона"
}

collect_evidence() {
  shopt -s nullglob
  logs=("$out"/*.jsonl)
  if [ ${#logs[@]} -eq 0 ]; then
    bridge=(build/ebt/*.jsonl)
    if [ ${#bridge[@]} -gt 0 ]; then
      cp "${bridge[@]}" "$out"/ || fail "копирование build/ebt в $out упало"
    fi
    logs=("$out"/*.jsonl)
  fi
  if [ ${#logs[@]} -eq 0 ]; then
    [ -n "$drifted" ] && echo "закреплённые копии отличаются от оригинала или отсутствуют (pinned.txt):$drifted" >&2
    fail "нет свидетельств ни в $out (OUT_DIR), ни в build/ebt/ (тесты: код $test_rc${runner_error:+, ошибка исполнения}), см. $run/test.log"
  fi
  # awk 1 добавляет перевод строки; checker получает исходные файлы с отдельными seq.
  awk 1 "${logs[@]}" > "$run/evidence.jsonl" || fail "склейка свидетельств упала"
}

check_evidence() {
  args=(--spec "$inputs/spec.toml" --evidence "${logs[@]}" --self-test
        --md "$run/report.md" --json "$run/report.json")
  [ -f "$inputs/checks.py" ] && args+=(--checkers "$inputs/checks.py")
  [ -f "$inputs/known.toml" ] && args+=(--known "$inputs/known.toml")
  [ -f "$inputs/baseline.jsonl" ] && args+=(--baseline "$inputs/baseline.jsonl")
  [ -n "${EBT_INV:-}" ] && args+=(--scope "$EBT_INV")
  exec 3> "$run/ebt-check.err" || fail "не удалось открыть ebt-check.err"
  "${checker[@]}" "${args[@]}" 2>&3
  check_rc=$?
  exec 3>&-
}

decide() {
  # Все наблюдённые причины, а не только определившая код выхода; пустые элементы отбрасывает gate.json.
  reasons=""
  case $check_rc in 0) ;; 1) reasons+=",checker_failed" ;; *) reasons+=",checker_error" ;; esac
  case $test_rc in 0) ;; 1) reasons+=",tests_failed" ;; *) reasons+=",tests_error" ;; esac
  [ -n "$protected" ] && reasons+=",protected_paths_changed"
  [ -n "$drifted" ] && reasons+=",pinned_drift"
  rc=$check_rc
  case $rc in 0|1|2) ;; *) rc=2 ;; esac
  [ $test_rc -ne 0 ] && [ $rc -eq 0 ] && rc=1
  [ -n "$protected" ] && [ $rc -eq 0 ] && rc=1
  [ -n "$drifted" ] && [ $rc -eq 0 ] && rc=1
  [ -n "$runner_error" ] && rc=2
  case $rc in 0) verdict="зелёный" ;; 1) verdict="красный" ;; *) verdict="ошибка гейта" ;; esac
}

write_report() {
  spec_hash=$(shasum -a 256 "$spec_file") || fail "не удалось хэшировать spec.toml"
  python_version=$("$py" --version) || fail "не удалось определить версию Python"
  if [ "$runner_kind" = test.sh ]; then
    runner_hash=$(shasum -a 256 "$ebt/test.sh") || fail "не удалось хэшировать test.sh"
    runner_environment="test.sh sha256 ${runner_hash:0:12}"
  else
    legacy_flutter_environment || fail "не удалось определить среду legacy Flutter adapter"
  fi
  # Сначала полностью построить текст, затем проверить единственную запись.
  report=$(cat <<EOF
# EBT-гейт: $verdict

- Коммит: \`$head\` в \`$clone\`
- Spec: \`$ebt\`, spec.toml sha256 ${spec_hash:0:12}
- Тесты \`$runner\`: код $test_rc · ebt_check: код $check_rc · логов склеено: ${#logs[@]}
- Поставка: $supply_name
- Чекер: $checker_name
- Покрытие требуется для: ${EBT_INV:-всех инвариантов spec}
- Среда: $runner_environment; $python_version
- Отчёт: [report.md](report.md)
EOF
) || fail "не удалось построить gate.md"
  [ -n "$runner_error" ] && report+=$'\n'"- **Ошибка исполнения тестов:** код $test_rc (договор: 0 — прошли, 1 — упали), см. test.log"
  [ -n "${BASE:-}" ] || report+=$'\n'"- Защищённые пути не проверялись: не задан BASE"
  [ -n "$protected" ] && report+=$'\n'"- **В ветке приложения изменены ebt/ или tool/ebt_check/:** $protected"
  [ -n "$drifted" ] && report+=$'\n'"- **Закреплённые копии отличаются от оригинала или отсутствуют (pinned.txt):**$drifted"
  printf '%s\n' "$report" > "$run/gate.md" || { rm -f "$run/gate.md"; fail "не удалось записать gate.md"; }
  summary "$rc" "$reasons" || { rm -f "$run/gate.md"; fail "не удалось записать gate.json"; }
  cat "$run/gate.md" || { rm -f "$run/gate.md"; fail "не удалось прочитать gate.md"; }
}

select_runner
preflight_git
snapshot_inputs
# Правки подготовки/тестов сохраняются даже при раннем отказе.
trap cleanup_exit EXIT
run_tests
verify_inputs
collect_evidence
check_evidence
decide
# Проверить stash до публикации PASS; при отказе EXIT повторит попытку сохранения.
stash_changes || fail "не удалось сохранить изменения прогона в git stash"
trap - EXIT
write_report
exit "$rc"
