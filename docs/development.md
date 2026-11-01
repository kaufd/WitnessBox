# Разработка

Нужны Python 3.11+ и `uv` для установки/сборки wheel и sdist. Runtime использует стандартную библиотеку. SDK-тесты требуют JDK 17+ и Bun.

Из корня репозитория:

```bash
make test        # source checker, установленный wheel-гейт и заготовка ebt/
make test-sdk    # Java, TypeScript и Dart SDK
make example     # пересобрать демонстрацию с четырьмя намеренными дефектами
make test-linux  # make test и make example для закоммиченного HEAD в Linux-контейнере
make release-check  # проверка выпуска: sdist → wheel, тесты из sdist, сравнение wheel
```

Workflow [test](../.github/workflows/test.yml) выполняет `make test example` на Linux и macOS (Python 3.11 и 3.13) и `make test-sdk` на каждый PR; `make test-linux` и `make release-check` остаются локальными.

Standalone artifacts собираются и проверяются отдельно:

```bash
uv build
uv tool install --force dist/witnessbox-0.6.0-py3-none-any.whl
```

Интеграционные тесты гейта устанавливают wheel во временное изолированное окружение; они проверяют поставку без editable install и без `PYTHONPATH`. Source-checker tests используют `PYTHONPATH=src` локально как тесты дерева разработки. Этот приём не нужен проектным расширениям: установленные чекеры импортируют типы через `witnessbox.api`.

`make release-check` собирает sdist и wheel из него, запускает из извлечённого sdist `make test example` и `make test-sdk` (если есть bun, javac и dart), сравнивает wheel из sdist с выпускным и ставит выпускной wheel в чистый venv без индекса, проверяя версию и отпечатки установки. Итог, версия и SHA-256 артефактов — в `build/release/<версия>/release.json`. `uv build` собирает sdist, а wheel — из него. `uv build --wheel` собирает напрямую из рабочего дерева и переиспользует устаревший `build/lib`: в wheel могут попасть удалённые из исходников модули, поэтому для выпуска и проверок используется только сборка через sdist.

Для `make test-linux` нужен работающий docker; образ задаёт `LINUX_IMAGE`. На Linux пропускается только проверка гейта без доступа к исходникам: она использует macOS `sandbox-exec`.

`make example` ожидаемо получает FAIL, потому что пример содержит четыре дефекта. Он также запускает self-test. При изменении чекера или классификации добавьте целевые случаи корректного свидетельства и каждого изменённого класса ошибки, затем запустите `make test` и `make example`. Изменения SDK требуют соответствующих тестов (`make test-sdk`). Подробные правила для изменений перечислены в корневом [CLAUDE.md](../CLAUDE.md).

## Выпуск

Публикуются ровно те файлы, которые проверил `make release-check`: workflow [publish](../.github/workflows/publish.yml) ничего не собирает, а скачивает wheel, sdist и `release.json` из GitHub Release тега, сверяет SHA-256 с `release.json` и загружает файлы через Trusted Publishing (D40).

1. Поднять `version` в `pyproject.toml`, закоммитить, выполнить `make release-check` — итог PASS в `build/release/<версия>/release.json`.
2. Поставить тег на этот коммит и отправить его: `git tag -a v<версия> -m ...`, `git push origin v<версия>`.
3. Создать prerelease с проверенными файлами: `gh release create v<версия> --prerelease build/release/<версия>/dist/* build/release/<версия>/release.json`.
4. Необязательно, пробный выпуск (нужен pending publisher на test.pypi.org с окружением `testpypi`): `gh workflow run publish.yml -f tag=v<версия> -f index=testpypi`, затем установка в чистое окружение — `uv tool run --default-index https://test.pypi.org/simple/ --from witnessbox==<версия> ebt-gate --installation` и `ebt-gate --scaffold` во временный каталог.
5. Выпуск: `gh workflow run publish.yml -f tag=v<версия> -f index=pypi`; SHA-256 файлов на PyPI сверить с `release.json`, проверить `uvx --from witnessbox==<версия> ebt-gate --installation` и `--scaffold`, затем `gh release edit v<версия> --prerelease=false --latest`.
6. Следующим коммитом — запись о выпуске с SHA-256 в журнале решений.

Повторно загрузить файл с той же версией PyPI не даёт, поэтому ошибка после шага 5 исправляется только новой версией.

## Совместимость импортов

Библиотечные импорты `from checkers import Verdict, WitnessError` и `from ebt_verification.api import Verdict, WitnessError` остаются совместимыми для установленной поставки: оба возвращают объекты из `witnessbox.api`. Внутренние модули старого пакета (`ebt_verification.checker.*`, `ebt_verification.cli`) не реэкспортируются: это не поддерживаемый интерфейс, их пути после переименования — `witnessbox.checker.*` и `witnessbox.cli`. Предпочтительный публичный импорт — `from witnessbox.api import Verdict, WitnessError`; новые шаблоны заготовки используют его. Ни shim каталога `tool/ebt_check`, ни symlink `lib/ebt` в текущем дереве исходников нет.
