#!/bin/bash
# Обновление ДокПоиск до последней версии. Документы, база и настройки сохраняются.
# Запуск:  bash update.sh
set -euo pipefail
cd "$(dirname "$0")"

if [[ -d .git ]]; then
  echo "==> Скачиваю обновления…"
  git pull --ff-only
else
  echo "Эта папка скачана ZIP-архивом, обновить её автоматически нельзя."
  echo "Скачайте новый ZIP с https://github.com/ilugly/docpoisk и запустите в новой папке: bash install.sh"
  exit 1
fi

exec bash install.sh
