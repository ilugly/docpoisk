"""Разбиение текста на чанки с перекрытием.

Режем «умно»: сначала пытаемся по абзацам, потом по строкам, предложениям,
словам — и только в крайнем случае посимвольно. Так чанк не обрывается
посреди предложения, и смысл пункта договора не теряется.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SEPARATORS = ["\n\n", "\n", ". ", "; ", ", ", " ", ""]


@dataclass
class Chunk:
    text: str
    page: int | None
    index: int


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"-\n(?=[а-яa-z])", "", text)        # переносы слов в PDF: «дого-\nвор»
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split(text: str, size: int, separators: list[str]) -> list[str]:
    """Рекурсивно режет текст на куски не длиннее size."""
    if len(text) <= size:
        return [text]
    sep, rest = separators[0], separators[1:]
    if sep == "":
        return [text[i : i + size] for i in range(0, len(text), size)]
    parts = text.split(sep)
    if len(parts) == 1:
        return _split(text, size, rest)
    pieces: list[str] = []
    for i, part in enumerate(parts):
        piece = part + (sep if i < len(parts) - 1 else "")
        if len(piece) > size:
            pieces.extend(_split(piece, size, rest))
        elif piece:
            pieces.append(piece)
    return pieces


def split_text(text: str, size: int, overlap: int) -> list[str]:
    pieces = _split(text, size, SEPARATORS)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > size:
            chunks.append(current.strip())
            # перекрытие: хвост предыдущего чанка, начиная с границы слова
            tail = current[-overlap:] if overlap else ""
            if " " in tail:
                tail = tail[tail.index(" ") + 1 :]
            current = tail
        current += piece
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) > 20 or len(chunks) == 1]


def chunk_pages(pages: list[tuple[int | None, str]], size: int, overlap: int) -> list[Chunk]:
    result: list[Chunk] = []
    for page_no, text in pages:
        for piece in split_text(normalize(text), size, overlap):
            result.append(Chunk(text=piece, page=page_no, index=len(result)))
    return result
