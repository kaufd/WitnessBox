#!/bin/bash
# Пример: зависимости для test.sh заготовки ts ставит Bun.
set -euo pipefail

bun install --frozen-lockfile
