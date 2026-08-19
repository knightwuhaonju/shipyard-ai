from dataclasses import FrozenInstanceError
from typing import Any, cast
from uuid import UUID

import pytest

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


def test_fitting_table_at_exact_decorated_boundary_stays_whole() -> None:
    path = ("Synthetic Rules", "Pumps")
    table = (
        ("Item", "Requirement"),
        ("A", "Independent synthetic pump"),
        ("B", "Emergency synthetic supply"),
        ("C", "Remote synthetic alarm"),
    )
    table_text = render_table(table)
    max_chars = len("Synthetic Rules > Pumps\n\n") + len(table_text)
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TABLE,
            text=table_text,
            structural_path=path,
            table=table,
        )
    )

    chunks = StructuralChunker(max_chars=max_chars).chunk(VERSION_ID, document)

    assert len(chunks) == 1
    assert chunks[0].normalized_text.endswith(table_text)


def test_oversized_table_uses_largest_consecutive_row_groups() -> None:
    header = ("Item", "Requirement")
    row_a = ("A", "Independent synthetic pump")
    row_b = ("B", "Emergency synthetic supply")
    row_c = ("C", "Remote synthetic alarm")
    table = (header, row_a, row_b, row_c)
    two_row_budget = len(render_table((header, row_a, row_b)))
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TABLE,
            text=render_table(table),
            table=table,
        )
    )

    chunks = StructuralChunker(max_chars=two_row_budget).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == [
        render_table((header, row_a, row_b)),
        render_table((header, row_c)),
    ]


def test_single_oversized_data_row_uses_bounded_text_fallback() -> None:
    header = ("Code", "Requirement")
    row = ("A", "abcdefghijklmnopqrstuvwxyz")
    table = (header, row)
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TABLE,
            text=render_table(table),
            table=table,
        )
    )

    chunks = StructuralChunker(max_chars=20).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == [
        "A",
        "abcdefghijklmnopqrst",
        "uvwxyz",
    ]
    assert all(chunk.normalized_text for chunk in chunks)
    assert all(len(chunk.normalized_text) <= 20 for chunk in chunks)


def test_oversized_table_header_uses_generic_canonical_tsv_fallback() -> None:
    table = (("ABCDEFGHIJK", "Column"), ("A", "value"))
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TABLE,
            text=render_table(table),
            table=table,
        )
    )

    first = StructuralChunker(max_chars=7).chunk(VERSION_ID, document)
    second = StructuralChunker(max_chars=7).chunk(VERSION_ID, document)

    assert first == second
    assert [chunk.normalized_text for chunk in first] == [
        "ABCDEFG",
        "HIJK",
        "Column",
        "A\tvalue",
    ]
    assert all(chunk.normalized_text for chunk in first)
    assert all(len(chunk.normalized_text) <= 7 for chunk in first)


def test_one_row_table_stays_whole_or_splits_deterministically_at_boundary() -> None:
    table = (("HeaderValue",),)
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.TABLE,
            text=render_table(table),
            table=table,
        )
    )

    fitting = StructuralChunker(max_chars=11).chunk(VERSION_ID, document)
    oversized = StructuralChunker(max_chars=5).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in fitting] == ["HeaderValue"]
    assert [chunk.normalized_text for chunk in oversized] == [
        "Heade",
        "rValu",
        "e",
    ]


def test_tables_never_merge_with_paragraphs_or_neighboring_tables() -> None:
    first_table = (("Header",), ("A",))
    second_table = (("Header",), ("B",))
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="before",
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.TABLE,
            text=render_table(first_table),
            table=first_table,
        ),
        ParsedBlock(
            ordinal=2,
            kind=ParsedBlockKind.TABLE,
            text=render_table(second_table),
            table=second_table,
        ),
        ParsedBlock(
            ordinal=3,
            kind=ParsedBlockKind.PARAGRAPH,
            text="after",
        ),
    )

    chunks = StructuralChunker().chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == [
        "before",
        "Header\nA",
        "Header\nB",
        "after",
    ]


def test_table_fragments_preserve_prefix_path_leaf_section_and_page() -> None:
    path = ("Rules",)
    table = (("H",), ("alpha",), ("bravo",))
    block = ParsedBlock(
        ordinal=0,
        kind=ParsedBlockKind.TABLE,
        text=render_table(table),
        structural_path=path,
        table=table,
    )
    # TABLE pages are not emitted by current Task 10 adapters. Injecting the
    # already-validated metadata keeps this test local to Task 3 preservation.
    object.__setattr__(block, "page", 4)
    document = _document(block)

    chunks = StructuralChunker(max_chars=12).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == [
        "Rules\n\nalpha",
        "Rules\n\nbravo",
    ]
    assert all(chunk.structural_path == path for chunk in chunks)
    assert all(chunk.section == "Rules" for chunk in chunks)
    assert all(chunk.page == 4 for chunk in chunks)
    assert all(chunk.normalized_text for chunk in chunks)
    assert all(len(chunk.normalized_text) <= 12 for chunk in chunks)


def test_different_version_id_changes_identity_without_changing_chunk_content() -> None:
    document = ParsedDocument(
        format=DocumentFormat.PDF,
        blocks=(
            ParsedBlock(
                ordinal=0,
                kind=ParsedBlockKind.PAGE,
                text="Synthetic Requirement applies to every vessel.",
                structural_path=("Synthetic Requirement",),
                page=2,
            ),
        ),
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
    assert [chunk.ordinal for chunk in first] == [chunk.ordinal for chunk in second]
    assert [chunk.page for chunk in first] == [chunk.page for chunk in second]
    assert [chunk.section for chunk in first] == [chunk.section for chunk in second]


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


def test_unstructured_fallback_splits_deterministically_without_overlap() -> None:
    first = "Synthetic pump requirement alpha."
    second = "Synthetic pump requirement beta."
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text=first,
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.PARAGRAPH,
            text=second,
        ),
    )

    chunks = StructuralChunker(max_chars=len(first)).chunk(VERSION_ID, document)

    assert [chunk.structural_path for chunk in chunks] == [(), ()]
    assert [chunk.section for chunk in chunks] == [None, None]
    actual = "".join("".join(chunk.normalized_text.split()) for chunk in chunks)
    expected = "".join((first + second).split())
    assert actual == expected
    assert all(len(chunk.normalized_text) <= len(first) for chunk in chunks)


def test_page_boundaries_propagate_across_bounded_page_splits() -> None:
    page_one = "alpha beta gamma delta"
    page_three = "omega page"
    document = ParsedDocument(
        format=DocumentFormat.PDF,
        blocks=(
            ParsedBlock(
                ordinal=0,
                kind=ParsedBlockKind.PAGE,
                text=page_one,
                page=1,
            ),
            ParsedBlock(
                ordinal=1,
                kind=ParsedBlockKind.PAGE,
                text=page_three,
                page=3,
            ),
        ),
    )

    chunks = StructuralChunker(max_chars=len("alpha beta gamma")).chunk(
        VERSION_ID, document
    )

    assert [chunk.page for chunk in chunks] == [1, 1, 3]
    assert "".join(chunks[0].normalized_text.split()) + "".join(
        chunks[1].normalized_text.split()
    ) == "".join(page_one.split())
    assert chunks[2].normalized_text == page_three


def test_decorated_body_at_exact_boundary_stays_in_one_chunk() -> None:
    path = ("S",)
    body = "abcde"
    max_chars = len("S\n\nabcde")
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text=body,
            structural_path=path,
        )
    )

    chunks = StructuralChunker(max_chars=max_chars).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == ["S\n\nabcde"]


def test_one_code_point_over_decorated_boundary_creates_two_chunks() -> None:
    path = ("S",)
    body = "abcdef"
    max_chars = len("S\n\nabcde")
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text=body,
            structural_path=path,
        )
    )

    chunks = StructuralChunker(max_chars=max_chars).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == ["S\n\nabcde", "S\n\nf"]


def test_fallback_prefers_newline_then_whitespace_boundaries() -> None:
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="alpha\nbeta gamma delta",
        )
    )

    chunks = StructuralChunker(max_chars=12).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == [
        "alpha",
        "beta gamma",
        "delta",
    ]


def test_fallback_single_word_uses_exact_code_point_slices_without_overlap() -> None:
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="abcdefghij",
        )
    )

    chunks = StructuralChunker(max_chars=4).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == ["abcd", "efgh", "ij"]
    assert "".join(chunk.normalized_text for chunk in chunks) == "abcdefghij"


def test_prefix_is_omitted_when_exact_boundary_leaves_no_body_room() -> None:
    path = ("S",)
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="ab",
            structural_path=path,
        )
    )

    chunks = StructuralChunker(max_chars=len("S\n\n")).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == ["ab"]
    assert chunks[0].structural_path == path
    assert chunks[0].section == "S"


def test_long_prefix_is_omitted_but_path_metadata_is_preserved() -> None:
    path = ("Very Long Heading",)
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="alpha",
            structural_path=path,
        )
    )

    chunks = StructuralChunker(max_chars=5).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == ["alpha"]
    assert chunks[0].structural_path == path
    assert chunks[0].section == "Very Long Heading"


def test_long_prefix_heading_only_path_splits_with_metadata() -> None:
    heading = "ExtremelyLongHeading"
    path = (heading,)
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.HEADING,
            text=heading,
            structural_path=path,
        )
    )

    chunks = StructuralChunker(max_chars=5).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks] == [
        "Extre",
        "melyL",
        "ongHe",
        "ading",
    ]
    assert all(chunk.structural_path == path for chunk in chunks)
    assert all(chunk.section == heading for chunk in chunks)
    assert all(len(chunk.normalized_text) <= 5 for chunk in chunks)


def test_empty_path_preamble_fallback_stays_local_to_headed_content() -> None:
    preamble = "synthetic preamble requires local fallback"
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text=preamble,
        ),
        ParsedBlock(
            ordinal=1,
            kind=ParsedBlockKind.HEADING,
            text="Rules",
            structural_path=("Rules",),
        ),
        ParsedBlock(
            ordinal=2,
            kind=ParsedBlockKind.PARAGRAPH,
            text="applies",
            structural_path=("Rules",),
        ),
    )

    chunks = StructuralChunker(max_chars=15).chunk(VERSION_ID, document)

    assert [chunk.normalized_text for chunk in chunks[:-1]] == [
        "synthetic",
        "preamble",
        "requires local",
        "fallback",
    ]
    assert all(chunk.structural_path == () for chunk in chunks[:-1])
    assert "".join(
        "".join(chunk.normalized_text.split()) for chunk in chunks[:-1]
    ) == "".join(preamble.split())
    assert chunks[-1].structural_path == ("Rules",)
    assert chunks[-1].normalized_text == "Rules\n\napplies"


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2000"])
def test_public_validation_rejects_invalid_character_budget(value: object) -> None:
    with pytest.raises(ValueError, match="^max_chars must be a positive integer$"):
        StructuralChunker(max_chars=cast(Any, value))


def test_public_validation_rejects_non_uuid_version_id() -> None:
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="synthetic requirement",
        )
    )

    with pytest.raises(ValueError, match="^version_id must be a UUID$"):
        StructuralChunker().chunk(cast(Any, str(VERSION_ID)), document)


def test_public_validation_rejects_parsed_document_subclass() -> None:
    class DerivedParsedDocument(ParsedDocument):
        pass

    document = DerivedParsedDocument(
        format=DocumentFormat.MARKDOWN,
        blocks=(
            ParsedBlock(
                ordinal=0,
                kind=ParsedBlockKind.PARAGRAPH,
                text="synthetic requirement",
            ),
        ),
    )

    with pytest.raises(ValueError, match="^document must be a ParsedDocument$"):
        StructuralChunker().chunk(VERSION_ID, cast(Any, document))


def test_public_validation_returns_immutable_exact_document_chunks() -> None:
    document = _document(
        ParsedBlock(
            ordinal=0,
            kind=ParsedBlockKind.PARAGRAPH,
            text="synthetic requirement",
        )
    )

    chunks = StructuralChunker().chunk(VERSION_ID, document)

    assert type(chunks) is tuple
    assert all(type(chunk) is DocumentChunk for chunk in chunks)
    with pytest.raises(FrozenInstanceError):
        setattr(chunks[0], "ordinal", 1)


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
