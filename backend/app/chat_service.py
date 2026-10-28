"""Сервис вопросов-ответов: вопрос → эмбеддинг → поиск в Qdrant → ответ LLM по найденным фрагментам.

Запускается отдельным контейнером `chat`. Ответ стримится в формате NDJSON:
сначала {"type":"sources",...}, потом много {"type":"token",...}, в конце {"type":"done"}.
"""
from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import config, ollama, store

log = logging.getLogger("chat")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Вопросы по документам")

SYSTEM_PROMPT = """Ты — ассистент, который отвечает на вопросы строго по предоставленным фрагментам документов (договоры, регламенты, судебные материалы и т.п.).

Правила:
1. Отвечай ТОЛЬКО на основе фрагментов из раздела «КОНТЕКСТ». Не используй общие знания и не выдумывай.
2. Если в контексте нет ответа — так и напиши: «В загруженных документах ответа на этот вопрос нет.»
3. Отвечай по-русски, кратко и точно: сначала прямой ответ, затем при необходимости пояснение.
4. После каждого утверждения указывай источник в квадратных скобках: [1], [2] — номер фрагмента из контекста.
5. Сохраняй точные формулировки: названия, суммы, сроки, даты, номера пунктов, наименования судов."""


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list)   # предыдущие реплики [{role, content}]
    doc_ids: list[str] | None = None                     # искать только в выбранных документах
    top_k: int | None = Field(default=None, ge=1, le=20)


def _context(hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        where = h["filename"] + (f", стр. {h['page']}" if h.get("page") else "")
        blocks.append(f"[{i}] ({where})\n{h['text']}")
    return "\n\n---\n\n".join(blocks)


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode()


@app.get("/health")
async def health():
    return {"ok": True, "models": await ollama.status()}


@app.post("/search")
async def search(req: Ask):
    """Только поиск фрагментов, без LLM — удобно для отладки качества поиска."""
    [vec] = await ollama.embed([req.question])
    return await store.search(vec, req.top_k or config.TOP_K, req.doc_ids)


@app.post("/ask")
async def ask(req: Ask):
    async def gen():
        try:
            [vec] = await ollama.embed([req.question])
            hits = await store.search(vec, req.top_k or config.TOP_K, req.doc_ids)
            yield _line({"type": "sources", "sources": [
                {"n": i, "filename": h["filename"], "page": h.get("page"), "score": h["score"],
                 "doc_id": h["doc_id"], "text": h["text"]}
                for i, h in enumerate(hits, start=1)
            ]})
            if not hits:
                yield _line({"type": "token", "text": "В загруженных документах не нашлось фрагментов, "
                             "относящихся к вопросу. Проверьте, что нужные документы загружены, "
                             "или переформулируйте вопрос."})
                yield _line({"type": "done"})
                return

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for m in req.history[-6:]:
                if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
                    messages.append({"role": m["role"], "content": m["content"][:4000]})
            messages.append({
                "role": "user",
                "content": f"КОНТЕКСТ:\n\n{_context(hits)}\n\n=====\n\nВОПРОС: {req.question}",
            })
            async for piece in ollama.chat_stream(messages):
                yield _line({"type": "token", "text": piece})
            yield _line({"type": "done"})
        except Exception as e:
            log.exception("Ошибка при ответе")
            yield _line({"type": "error", "error": str(e)})

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
