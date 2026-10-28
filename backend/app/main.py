"""Всё в одном процессе: индексация + чат + веб-интерфейс.

Используется настольным приложением (app/desktop.py). Docker-вариант запускает
ingest_service и chat_service отдельными контейнерами — код тот же.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import chat_service, ingest_service

WEB_DIR = Path(os.getenv("WEB_DIR", Path(__file__).resolve().parents[2] / "web"))

app = FastAPI(title="ДокПоиск")
app.mount("/api/ingest", ingest_service.app)
app.mount("/api/chat", chat_service.app)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
