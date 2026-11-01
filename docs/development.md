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

Standalone artifacts собираются и проверяются отдельно:

```bash
uv build --wheel --sdist
uv tool install --force dist/witnessbox-0.4.0-py3-none-any.whl
```

Интеграционные тесты гейта устанавливают wheel во временное изолированное окружение; они проверяют поставку без editable install и без `PYTHONPATH`. Source-checker tests используют `PYTHONPATH=src` локально как тесты дерева разработки. Этот приём не нужен проектным расширениям: установленные чекеры импортируют типы через `ebt_verification.api`.

`make release-check` собирает sdist и wheel из него, запускает из извлечённого sdist `make test example` и `make test-sdk` (если есть bun, javac и dart), сравнивает wheel из sdist с выпускным и ставит выпускной wheel в чистый venv без индекса, проверяя версию и отпечатки установки. Итог, версия и SHA-256 артефактов — в `build/release/<версия>/release.json`. Wheel собирается только из sdist: прямая сборка из рабочего дерева переиспользует устаревший `build/lib`.

Для `make test-linux` нужен работающий docker; образ задаёт `LINUX_IMAGE`. На Linux пропускается только проверка гейта без доступа к исходникам: она использует macOS `sandbox-exec`.

`make example` ожидаемо получает FAIL, потому что пример содержит четыре дефекта. Он также запускает self-test. При изменении чекера или классификации добавьте целевые случаи корректного свидетельства и каждого изменённого класса ошибки, затем запустите `make test` и `make example`. Изменения SDK требуют соответствующих тестов (`make test-sdk`). Подробные правила для изменений перечислены в корневом [CLAUDE.md](../CLAUDE.md).

## Совместимость импортов

Библиотечные импорты `from checkers import Verdict, WitnessError` остаются совместимыми для установленной поставки. Предпочтительный публичный импорт — `from ebt_verification.api import Verdict, WitnessError`. Ни shim каталога `tool/ebt_check`, ни symlink `lib/ebt` в текущем дереве исходников нет.
