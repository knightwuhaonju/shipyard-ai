from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from services.ingestion import OcrPage, OcrPort


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
