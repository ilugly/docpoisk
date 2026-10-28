#!/bin/bash
# Запуск ДокПоиск из терминала (после ./install.sh).
#   ./run.sh            — окно приложения
#   ./run.sh --browser  — открыть в браузере (если окно по какой-то причине не открывается)
cd "$(dirname "$0")/backend"
exec ../.venv/bin/python -m app.desktop "$@"
