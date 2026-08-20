from dataclasses import FrozenInstanceError
from typing import cast

import pytest

import services.ingestion.parser as parser_contract
from adapters.ocr import FakeOcrAdapter
from adapters.parsers import PdfParser, TxtParser
from services.ingestion import (
    DocumentFormat,
    OcrFallbackParser,
    OcrPage,
    OcrPort,
    ParsedBlockKind,
    ParserError,
    ParserErrorCode,
)
from tests.fixtures.parser_documents import (
    blank_pdf_bytes,
    encrypted_pdf_bytes,
    synthetic_pdf_bytes,
)


def test_textless_pdf_requires_ocr_before_task_012_fallback_exists() -> None:
    with pytest.raises(ParserError) as captured:
        PdfParser().parse(blank_pdf_bytes())

    assert captured.value.code is ParserErrorCode.OCR_REQUIRED
    assert str(captured.value) == "PDF has no extractable text layer"


def test_injected_fake_ocr_preserves_original_page_numbers() -> None:
    content = blank_pdf_bytes()
    fake = FakeOcrAdapter(
        (
            OcrPage(page=1, text="  Synthetic OCR page one  "),
            OcrPage(page=3, text="Synthetic OCR page three"),
        )
    )

    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(content)

    assert parsed.format is DocumentFormat.PDF
    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.PAGE,
        ParsedBlockKind.PAGE,
    ]
    assert [block.ordinal for block in parsed.blocks] == [0, 1]
    assert [block.page for block in parsed.blocks] == [1, 3]
    assert [block.text for block in parsed.blocks] == [
        "Synthetic OCR page one",
        "Synthetic OCR page three",
    ]
    assert fake.received_contents == (content,)
    assert _accept_port(fake) is fake


def test_ocr_is_disabled_by_default() -> None:
    with pytest.raises(ParserError) as captured:
        OcrFallbackParser(PdfParser()).parse(blank_pdf_bytes())
    assert captured.value.code is ParserErrorCode.OCR_REQUIRED


def test_text_layer_pdf_bypasses_injected_ocr() -> None:
    fake = FakeOcrAdapter((OcrPage(page=1, text="must not run"),))
    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(synthetic_pdf_bytes())
    assert [block.page for block in parsed.blocks] == [1, 2]
    assert fake.received_contents == ()


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", ParserErrorCode.EMPTY_DOCUMENT),
        (encrypted_pdf_bytes(), ParserErrorCode.ENCRYPTED_DOCUMENT),
        (b"%PDF-1.4\nnot a PDF", ParserErrorCode.INVALID_DOCUMENT),
        (
            b"x" * (parser_contract.MAX_SOURCE_BYTES + 1),
            ParserErrorCode.RESOURCE_LIMIT,
        ),
    ],
    ids=["empty", "encrypted", "malformed", "resource-limit"],
)
def test_non_ocr_required_primary_errors_bypass_ocr(
    content: bytes, code: ParserErrorCode
) -> None:
    fake = FakeOcrAdapter((OcrPage(page=1, text="must not run"),))

    with pytest.raises(ParserError) as captured:
        OcrFallbackParser(PdfParser(), ocr=fake).parse(content)

    assert captured.value.code is code
    assert fake.received_contents == ()


def test_ocr_fallback_rejects_non_pdf_primary_parser() -> None:
    with pytest.raises(ValueError, match="^primary parser must use PDF format$"):
        OcrFallbackParser(TxtParser())


def test_blank_ocr_page_preserves_later_page_gap() -> None:
    fake = FakeOcrAdapter(
        (
            OcrPage(page=1, text=" \t\r\n "),
            OcrPage(page=3, text="  Synthetic third page  "),
        )
    )

    parsed = OcrFallbackParser(PdfParser(), ocr=fake).parse(blank_pdf_bytes())

    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].ordinal == 0
    assert parsed.blocks[0].page == 3
    assert parsed.blocks[0].text == "Synthetic third page"


@pytest.mark.parametrize("pages", [[], (object(),)])
def test_fake_ocr_rejects_invalid_configured_pages(pages: object) -> None:
    with pytest.raises(ValueError, match="^pages must be a tuple of OcrPage$"):
        FakeOcrAdapter(cast(tuple[OcrPage, ...], pages))


def test_fake_ocr_returns_configured_pages_and_immutable_history() -> None:
    pages = (OcrPage(page=2, text="Synthetic page"),)
    fake = FakeOcrAdapter(pages)

    returned = fake.recognize_pdf(b"first")
    first_history = fake.received_contents
    fake.recognize_pdf(b"second")

    assert returned is pages
    assert type(first_history) is tuple
    assert first_history == (b"first",)
    assert fake.received_contents == (b"first", b"second")


def test_ocr_page_is_an_exact_immutable_port_record() -> None:
    page = OcrPage(page=3, text="  synthetic OCR text  ")

    assert type(page) is OcrPage
    assert page.page == 3
    assert page.text == "  synthetic OCR text  "
    with pytest.raises(FrozenInstanceError):
        page.page = 4  # type: ignore[misc]


def _accept_port(port: OcrPort) -> OcrPort:
    return port


@pytest.mark.parametrize("page", [0, -1, True, 1.0, "1"])
def test_ocr_page_rejects_invalid_page(page: object) -> None:
    with pytest.raises(ValueError, match="^page must be a positive integer$"):
        OcrPage(page=cast(int, page), text="synthetic")


@pytest.mark.parametrize("text", [None, b"text", "bad\x00text"])
def test_ocr_page_rejects_invalid_text(text: object) -> None:
    with pytest.raises(ValueError, match="^text must be a string without NUL$"):
        OcrPage(page=1, text=cast(str, text))


def test_ocr_page_accepts_blank_processed_text() -> None:
    page = OcrPage(page=1, text="")

    assert page.text == ""
