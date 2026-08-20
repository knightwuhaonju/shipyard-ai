"""Deterministic OCR adapter for tests and local contract checks."""

from services.ingestion.ocr import OcrPage


class FakeOcrAdapter:
    def __init__(self, pages: tuple[OcrPage, ...]) -> None:
        if type(pages) is not tuple or any(type(page) is not OcrPage for page in pages):
            raise ValueError("pages must be a tuple of OcrPage")
        self._pages = pages
        self._received_contents: list[bytes] = []

    @property
    def received_contents(self) -> tuple[bytes, ...]:
        return tuple(self._received_contents)

    def recognize_pdf(self, content: bytes) -> tuple[OcrPage, ...]:
        self._received_contents.append(content)
        return self._pages
