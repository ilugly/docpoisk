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

SYSTEM_PROMPT = """Ты — ассистент, который отвечает на вопросы строго по фрагментам документов (договоры, регламенты, судебные материалы и т.п.).

Правила:
1. Используй ТОЛЬКО факты из фрагментов. Не добавляй общих знаний и ничего не выдумывай.
2. Найди фрагмент, где прямо говорится об ответе, и перескажи его близко к тексту. Числа, проценты, суммы, сроки, даты, ФИО, названия судов и организаций переписывай из фрагмента дословно, не пересчитывай и не меняй.
3. Начинай сразу с ответа по существу, не повторяй вопрос.
4. В конце каждого утверждения ставь номер фрагмента, из которого оно взято, например [2].
5. Если во фрагментах ответа нет — ответь одной фразой: «В загруженных документах ответа на этот вопрос нет.»
6. Пиши по-русски, кратко."""

USER_TEMPLATE = """Фрагменты документов:

{context}

=====
Вопрос: {question}

Ответь на вопрос по фрагментам выше. Значения переписывай дословно, после каждого утверждения укажи номер фрагмента в квадратных скобках."""


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list)   # предыдущие реплики [{role, content}]
    doc_ids: list[str] | None = None                     # искать только в выбранных документах
    top_k: int | None = Field(default=None, ge=1, le=20)


def _context(hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        where = h["filename"] + (f", стр. {h['page']}" if h.get("page") else "")
        blocks.append(f"Фрагмент [{i}] — {where}:\n{h['text']}")
    return "\n\n".join(blocks)


async def _retrieve(question: str, top_k: int | None, doc_ids: list[str] | None) -> list[dict]:
    [vec] = await ollama.embed([question])
    hits = await store.search(vec, top_k or config.TOP_K, doc_ids)
    if hits:
        # Отбрасываем фрагменты, заметно менее похожие, чем лучший: меньше шума — меньше путаницы у модели
        best = hits[0]["score"]
        hits = [h for h in hits if h["score"] >= best - config.REL_SCORE_GAP]
    return hits


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode()


@app.get("/health")
async def health():
    return {"ok": True, "models": await ollama.status()}


@app.post("/search")
async def search(req: Ask):
    """Только поиск фрагментов, без LLM — удобно для отладки качества поиска."""
    return await _retrieve(req.question, req.top_k, req.doc_ids)


@app.post("/ask")
async def ask(req: Ask):
    async def gen():
        try:
            hits = await _retrieve(req.question, req.top_k, req.doc_ids)
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
