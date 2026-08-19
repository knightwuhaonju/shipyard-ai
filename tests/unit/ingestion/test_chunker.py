from uuid import UUID

from packages.domain import DocumentChunk, document_chunk_id
from services.ingestion.chunker import StructuralChunker
from services.ingestion.parser import (
    DocumentFormat,
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    render_table,
)

VERSION_ID = UUID("91000000-0000-0000-0000-000000000001")


def _document(*blocks: ParsedBlock) -> ParsedDocument:
    return ParsedDocument(format=DocumentFormat.MARKDOWN, blocks=blocks)


def test_class_rule_hierarchy_produces_deterministic_structural_chunks() -> None:
    table = (("Item", "Requirement"), ("Pump", "Two independent units"))
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TITLE,
            text="Synthetic Class Rules",
            structural_path=("Synthetic Class Rules",),
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.HEADING,
            text="Chapter 3",
            structural_path=("Synthetic Class Rules", "Chapter 3"),
        ),
        ParsedBlock(
            ordinal=2,
            kind=ParsedBlockKind.HEADING,
            text="Fire Pumps",
            structural_path=("Synthetic Class Rules", "Chapter 3", "Fire Pumps"),
        ),
        ParsedBlock(
            ordinal=3,
            kind=ParsedBlockKind.PARAGRAPH,
            text="Each synthetic vessel has an independently driven fire pump.",
            structural_path=("Synthetic Class Rules", "Chapter 3", "Fire Pumps"),
        ),
        ParsedBlock(
            ordinal=4,
            kind=ParsedBlockKind.PARAGRAPH,
            text="The second synthetic pump remains available after one failure.",
            structural_path=("Synthetic Class Rules", "Chapter 3", "Fire Pumps"),
        ),
        ParsedBlock(
            ordinal=5,
            kind=ParsedBlockKind.TABLE,
            text=render_table(table),
            structural_path=("Synthetic Class Rules", "Chapter 3", "Fire Pumps"),
            table=table,
        ),
    )

    first = StructuralChunker().chunk(VERSION_ID, document)
    second = StructuralChunker().chunk(VERSION_ID, document)

    assert first == second
    assert len(first) == 2
    assert [chunk.ordinal for chunk in first] == [0, 1]
    assert all(type(chunk) is DocumentChunk for chunk in first)
    assert all(
        chunk.chunk_id
        == document_chunk_id(VERSION_ID, chunk.structural_path, chunk.ordinal)
        for chunk in first
    )
    assert first[0].structural_path == (
        "Synthetic Class Rules",
        "Chapter 3",
        "Fire Pumps",
    )
    assert first[0].section == "Fire Pumps"
    assert first[0].normalized_text.startswith(
        "Synthetic Class Rules > Chapter 3 > Fire Pumps\n\n"
    )
    assert "one failure" in first[0].normalized_text
    assert first[1].normalized_text.endswith(render_table(table))


def test_different_version_id_changes_identity_without_changing_chunk_content() -> None:
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="Synthetic Requirement applies to every vessel.",
        )
    )

    first = StructuralChunker().chunk(VERSION_ID, document)
    second = StructuralChunker().chunk(
        UUID("91000000-0000-0000-0000-000000000002"), document
    )

    assert [chunk.chunk_id for chunk in first] != [chunk.chunk_id for chunk in second]
    assert [chunk.normalized_text for chunk in first] == [
        chunk.normalized_text for chunk in second
    ]
    assert [chunk.structural_path for chunk in first] == [
        chunk.structural_path for chunk in second
    ]


def test_marker_for_wholly_empty_sibling_subtree_emits_exactly_one_chunk() -> None:
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.HEADING,
            text="Chapter 4",
            structural_path=("Chapter 4",),
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.HEADING,
            text="Steering Gear",
            structural_path=("Chapter 4", "Steering Gear"),
        ),
        ParsedBlock(
            ordinal=2,
            kind=ParsedBlockKind.HEADING,
            text="Synthetic Requirement",
            structural_path=("Chapter 4", "Synthetic Requirement"),
        ),
        ParsedBlock(
            ordinal=3,
            kind=ParsedBlockKind.PARAGRAPH,
            text="Synthetic Requirement is verified before delivery.",
            structural_path=("Chapter 4", "Synthetic Requirement"),
        ),
    )

    chunks = StructuralChunker().chunk(VERSION_ID, document)

    assert len(chunks) == 2
    assert [chunk.section for chunk in chunks] == [
        "Steering Gear",
        "Synthetic Requirement",
    ]
    assert chunks[0].normalized_text.endswith("Steering Gear")
    assert "Chapter 4\n\nChapter 4" not in [
        chunk.normalized_text for chunk in chunks
    ]


def test_paragraph_regions_with_different_structural_paths_never_merge() -> None:
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="Steering Gear undergoes an alignment check.",
            structural_path=("Chapter 4", "Steering Gear"),
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.PARAGRAPH,
            text="Synthetic Requirement undergoes a witness check.",
            structural_path=("Chapter 4", "Synthetic Requirement"),
        ),
    )

    chunks = StructuralChunker().chunk(VERSION_ID, document)

    assert len(chunks) == 2
    assert [chunk.section for chunk in chunks] == [
        "Steering Gear",
        "Synthetic Requirement",
    ]
    assert "witness check" not in chunks[0].normalized_text
    assert "alignment check" not in chunks[1].normalized_text


def test_ordinals_are_global_and_contiguous_across_draft_kinds() -> None:
    table = (("Item", "Requirement"), ("Gear", "One spare actuator"))
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.HEADING,
            text="Chapter 4",
            structural_path=("Chapter 4",),
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.PARAGRAPH,
            text="Chapter 4 establishes the steering standard.",
            structural_path=("Chapter 4",),
        ),
        ParsedBlock(
            ordinal=2,
            kind=ParsedBlockKind.HEADING,
            text="Steering Gear",
            structural_path=("Chapter 4", "Steering Gear"),
        ),
        ParsedBlock(
            ordinal=3,
            kind=ParsedBlockKind.HEADING,
            text="Synthetic Requirement",
            structural_path=("Chapter 4", "Synthetic Requirement"),
        ),
        ParsedBlock(
            ordinal=4,
            kind=ParsedBlockKind.PARAGRAPH,
            text="Synthetic Requirement needs a signed test record.",
            structural_path=("Chapter 4", "Synthetic Requirement"),
        ),
        ParsedBlock(
            ordinal=5,
            kind=ParsedBlockKind.TABLE,
            text=render_table(table),
            structural_path=("Chapter 4", "Synthetic Requirement"),
            table=table,
        ),
    )

    chunks = StructuralChunker().chunk(VERSION_ID, document)

    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2, 3]
    assert [chunk.section for chunk in chunks] == [
        "Chapter 4",
        "Steering Gear",
        "Synthetic Requirement",
        "Synthetic Requirement",
    ]
    assert chunks[-1].normalized_text.endswith(render_table(table))
