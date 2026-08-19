"""Deterministic structure-aware conversion of parser blocks to document chunks."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from packages.domain import DocumentChunk, document_chunk_id
from services.ingestion.parser import ParsedBlock, ParsedBlockKind, ParsedDocument

DEFAULT_MAX_CHARS = 2_000


@dataclass(frozen=True, slots=True)
class _ChunkDraft:
    structural_path: tuple[str, ...]
    normalized_text: str
    page: int | None


@dataclass(frozen=True, slots=True)
class _Marker:
    structural_path: tuple[str, ...]
    text: str
    page: int | None


class StructuralChunker:
    def __init__(self, *, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        if type(max_chars) is not int or max_chars <= 0:
            raise ValueError("max_chars must be a positive integer")
        self._max_chars = max_chars

    def chunk(
        self, version_id: UUID, document: ParsedDocument
    ) -> tuple[DocumentChunk, ...]:
        if type(version_id) is not UUID:
            raise ValueError("version_id must be a UUID")
        if type(document) is not ParsedDocument:
            raise ValueError("document must be a ParsedDocument")
        drafts = _structured_drafts(document.blocks, self._max_chars)
        return _materialize(version_id, drafts)


def _context_prefix(path: tuple[str, ...]) -> str:
    return " > ".join(path)


def _body_budget(path: tuple[str, ...], max_chars: int) -> tuple[str, int]:
    prefix = _context_prefix(path)
    if prefix and len(prefix) + 2 < max_chars:
        return prefix, max_chars - len(prefix) - 2
    return "", max_chars


def _decorate(path: tuple[str, ...], body: str, max_chars: int) -> str:
    prefix, body_budget = _body_budget(path, max_chars)
    assert len(body) <= body_budget
    normalized_text = f"{prefix}\n\n{body}" if prefix else body
    assert len(normalized_text) <= max_chars
    return normalized_text


def _materialize(
    version_id: UUID, drafts: list[_ChunkDraft]
) -> tuple[DocumentChunk, ...]:
    return tuple(
        DocumentChunk(
            chunk_id=document_chunk_id(version_id, draft.structural_path, ordinal),
            version_id=version_id,
            structural_path=draft.structural_path,
            ordinal=ordinal,
            normalized_text=draft.normalized_text,
            page=draft.page,
            section=draft.structural_path[-1] if draft.structural_path else None,
        )
        for ordinal, draft in enumerate(drafts)
    )


def _structured_drafts(
    blocks: tuple[ParsedBlock, ...], max_chars: int
) -> list[_ChunkDraft]:
    drafts: list[_ChunkDraft] = []
    markers: list[_Marker] = []
    paragraph_context: tuple[tuple[str, ...], int | None] | None = None
    paragraphs: list[str] = []

    def flush_paragraphs() -> None:
        nonlocal paragraph_context
        if paragraph_context is None:
            return
        path, page = paragraph_context
        drafts.append(
            _ChunkDraft(
                structural_path=path,
                normalized_text=_decorate(path, "\n\n".join(paragraphs), max_chars),
                page=page,
            )
        )
        paragraph_context = None
        paragraphs.clear()

    def flush_departed_markers(candidate_path: tuple[str, ...]) -> None:
        remaining_markers: list[_Marker] = []
        for marker in markers:
            if _is_descendant_path(candidate_path, marker.structural_path):
                remaining_markers.append(marker)
                continue
            drafts.append(
                _ChunkDraft(
                    structural_path=marker.structural_path,
                    normalized_text=_decorate(
                        marker.structural_path, marker.text, max_chars
                    ),
                    page=marker.page,
                )
            )
        markers[:] = remaining_markers

    for block in blocks:
        if block.kind in (ParsedBlockKind.TITLE, ParsedBlockKind.HEADING):
            flush_paragraphs()
            flush_departed_markers(block.structural_path)
            markers.append(
                _Marker(
                    structural_path=block.structural_path,
                    text=block.text,
                    page=block.page,
                )
            )
            continue

        flush_departed_markers(block.structural_path)
        markers[:] = [
            marker
            for marker in markers
            if not _is_descendant_path(block.structural_path, marker.structural_path)
        ]

        if block.kind is ParsedBlockKind.TABLE:
            flush_paragraphs()
            drafts.append(
                _ChunkDraft(
                    structural_path=block.structural_path,
                    normalized_text=_decorate(
                        block.structural_path, block.text, max_chars
                    ),
                    page=block.page,
                )
            )
            continue

        context = (block.structural_path, block.page)
        if paragraph_context != context:
            flush_paragraphs()
            paragraph_context = context
        paragraphs.append(block.text)

    flush_paragraphs()
    flush_departed_markers(())
    return drafts


def _is_descendant_path(
    candidate_path: tuple[str, ...], marker_path: tuple[str, ...]
) -> bool:
    return candidate_path[: len(marker_path)] == marker_path
