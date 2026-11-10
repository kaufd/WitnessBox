# Модель угроз Witnessbox

[English](security.md) · **Русский**

Гейт и чекер отвечают на вопрос «что записано и согласуется ли запись с правилом», а не «что исполнялось». Противник — код под проверкой и его автор, в том числе агент-кодировщик; он работает от того же пользователя ОС, что и гейт. Гарантия — **обнаружение** несоответствия, а не граница прав: гейт не песочница и не доказательство отсутствия обхода (D26).

| Атака или ошибка | Чем ловится | Ссылка |
|---|---|---|
| Код пишет `ok: true` при неверном решении | чекер пересчитывает правило по `data`; `ok` не влияет; `FALSE_PROOF` | [test_ok_field_is_ignored_for_verdict](../tests/checker/test_checker.py), [test_false_proof](../tests/checker/test_checker.py) |
| Запись потеряна внутри файла | `LOG_GAP` по `seq` | [test_log_gap](../tests/checker/test_checker.py), [test_gap_at_file_boundary](../tests/checker/test_checker.py) |
| Сценарий пропал относительно baseline | дыра в покрытии | [test_vanished_scenario_is_a_gap](../tests/checker/test_checker.py) |
| Неполное или неверного типа свидетельство | `WITNESS_INCOMPLETE`, `WITNESS_MALFORMED`, `MALFORMED_LINE` | [test_wrong_types_are_malformed](../tests/checker/test_checker.py), [test_non_string_ids_are_malformed_lines](../tests/checker/test_checker.py) |
| Чекер не смотрит на поле | `--self-test` | [test_self_test_finds_ignored_field](../tests/checker/test_checker.py) |
| Чекер проверяет только часть списка | `weak_paths` из self-test, путь `поле[i]…` | [test_self_test_finds_checker_reading_only_first_list_element](../tests/checker/test_checker.py) |
| Класс входов не покрыт | `uncovered_partitions`, FAIL без `--allow-uncovered` | [test_coverage](../tests/checker/test_checker.py) |
| Тесты упали, а чекер зелёный | `tests_failed`, FAIL | [D19](decisions.ru.md) |
| Ветка правит `ebt/` или `tool/ebt_check/` | `protected_paths_changed`; нужен `BASE` | [gate.sh](../src/witnessbox/gate.sh) |
| Ветка правит закреплённую копию SDK | `pinned_drift` | `pinned.txt`, [D25](decisions.ru.md) |
| Входы проверки изменены во время прогона | снимок `inputs/`, ERROR `gate_error` | [D26](decisions.ru.md) |
| Код гейта или чекера изменён во время прогона | сверка `--installation`, ERROR | [D26](decisions.ru.md) |
| Свидетельств нет | ERROR | [docs/usage.md](usage.ru.md) |
| Свидетельства подменены после вердикта | `evidence` в `gate.json`, перепроверка `witnessbox check` | [D34](decisions.ru.md) |
| Вердикт или `gate.json` изменены кодом проекта (CI-режим) | перепроверка в `workflow_run`, `gate.json` подписан аттестацией | [test_verify.py](../tests/actions/test_verify.py), [D45](decisions.ru.md) |
| Spec изменена в PR (CI-режим) | `ebt/` и `checks.py` из `BASE`; `protected_paths_changed` | [test_prepare_uses_base_spec_and_drops_prepare](../tests/actions/test_verify.py), [D45](decisions.ru.md) |
| Ветка PR правит `ebt-verify.yml` | GitHub берёт workflow из основной ветки; PR-версия не исполняется | [D45](decisions.ru.md) |
| Враждебный вход ломает чекер | код 0/1/2 без traceback | [HostileEvidence](../tests/checker/test_checker.py) |
| Устаревший PASS в каталоге результатов | очистка до запуска, атомарная запись, удаление при сбое | [D19](decisions.ru.md) |

Согласованная подмена свидетельств и `gate.json` после вердикта не ловится при локальном запуске и в первой стадии CI: `evidence` — хеш, а не подпись, и тот же пользователь может переписать оба файла (D34). Хеш обнаруживает расхождение с файлами, которые читал чекер, а не доказывает их подлинность. В CI-режиме вторая стадия перепроверяет свидетельства и подписывает `gate.json` аттестацией (D45), поэтому подмена после вердикта обнаруживается при проверке подписи.

## Не ловится

- Решение принято, но не записано, и в сценариях OBS не видно его последствий — [D29](decisions.ru.md). Мутационный аудит при этом остаётся исследованием, а не гейтом.
- Установка подменена до прогона — вызывающий сверяет `gate_sha256` и `checker_sha256` с выпускными значениями ([D33](decisions.ru.md)); в CI `actions/setup` сверяет wheel и `--installation` с `release.json` ([D45](decisions.ru.md)).
- Намеренный обход из `test.sh` тем же пользователем: фоновый процесс, `~/.gitconfig`, `PATH` ([D26](decisions.ru.md)); в CI это относится к первой стадии `ebt-tests`, вторая стадия код проекта не исполняет.
- Согласованная подмена свидетельств и `gate.json` до вердикта: свидетельства пишет код под проверкой, а `tests_exit_code` первой стадии — заявление этого кода ([D45](decisions.ru.md)). Подпись второй стадии обнаруживает подмену после вердикта, но не доказывает, что свидетельства отражают реальное исполнение.
- PR из форка или push без PR: у `workflow_run` обычно нет `BASE`, а явный форк отвергается по `head_repository`; статус — `error`, а не `success` ([D45](decisions.ru.md)).
- Правка файла свидетельств между чтением чекером и записью итога ([D34](decisions.ru.md)).
- Неверная спецификация — её утверждает человек ([D4](decisions.ru.md)).

Каждая строка «ловится» ссылается на тест или решение. Новый класс атак добавляется в таблицу вместе с тестом; строку без такой ссылки следует перенести в «Не ловится».
