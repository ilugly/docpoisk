"""Работа с векторной базой Qdrant (метрика — косинусная близость)."""
from __future__ import annotations

import uuid

from qdrant_client import AsyncQdrantClient, models

from . import config

_client: AsyncQdrantClient | None = None


def client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        if config.QDRANT_URL:
            _client = AsyncQdrantClient(url=config.QDRANT_URL, timeout=60)
        else:
            _client = AsyncQdrantClient(path=config.QDRANT_PATH)  # встроенный режим, без сервера
    return _client


async def ensure_collection(dim: int) -> None:
    c = client()
    if await c.collection_exists(config.COLLECTION):
        info = await c.get_collection(config.COLLECTION)
        current = info.config.params.vectors.size
        if current != dim:
            raise RuntimeError(
                f"Коллекция создана для эмбеддингов размера {current}, а модель {config.EMBED_MODEL} "
                f"даёт {dim}. Сменили EMBED_MODEL? Удалите папку с базой "
                f"({config.QDRANT_PATH}) и загрузите документы заново."
            )
        return
    await c.create_collection(
        config.COLLECTION,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )
    if config.QDRANT_URL:  # индексы полей есть только у сервера; во встроенном режиме не нужны
        await c.create_payload_index(config.COLLECTION, "doc_id", models.PayloadSchemaType.KEYWORD)


async def upsert(doc_id: str, filename: str, chunks, vectors, uploaded_at: str) -> None:
    points = [
        models.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{ch.index}")),
            vector=vec,
            payload={
                "doc_id": doc_id,
                "filename": filename,
                "page": ch.page,
                "chunk": ch.index,
                "text": ch.text,
                "uploaded_at": uploaded_at,
            },
        )
        for ch, vec in zip(chunks, vectors)
    ]
    for i in range(0, len(points), 256):
        await client().upsert(config.COLLECTION, points=points[i : i + 256], wait=True)


def _doc_filter(doc_ids: list[str] | None):
    if not doc_ids:
        return None
    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids))])


async def search(vector: list[float], limit: int, doc_ids: list[str] | None = None) -> list[dict]:
    if not await client().collection_exists(config.COLLECTION):
        return []
    res = await client().query_points(
        config.COLLECTION,
        query=vector,
        limit=limit,
        query_filter=_doc_filter(doc_ids),
        with_payload=True,
        score_threshold=config.MIN_SCORE,
    )
    return [{**p.payload, "score": round(p.score, 4)} for p in res.points]


async def delete_doc(doc_id: str) -> None:
    if await client().collection_exists(config.COLLECTION):
        await client().delete(config.COLLECTION, points_selector=_doc_filter([doc_id]), wait=True)


async def list_docs() -> list[dict]:
    """Список документов: собираем по первому чанку каждого документа."""
    if not await client().collection_exists(config.COLLECTION):
        return []
    docs: dict[str, dict] = {}
    offset = None
    while True:
        points, offset = await client().scroll(
            config.COLLECTION,
            limit=1000,
            offset=offset,
            with_payload=["doc_id", "filename", "uploaded_at"],
            with_vectors=False,
        )
        for p in points:
            d = docs.setdefault(
                p.payload["doc_id"],
                {"doc_id": p.payload["doc_id"], "filename": p.payload["filename"],
                 "uploaded_at": p.payload.get("uploaded_at"), "chunks": 0},
            )
            d["chunks"] += 1
        if offset is None:
            break
    return sorted(docs.values(), key=lambda d: d.get("uploaded_at") or "", reverse=True)
