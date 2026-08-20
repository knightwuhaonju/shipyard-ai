"""Optional, engine-independent PDF OCR service boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class OcrPage:
    page: int
    text: str

    def __post_init__(self) -> None:
        if type(self.page) is not int or self.page <= 0:
            raise ValueError("page must be a positive integer")
        if type(self.text) is not str or "\x00" in self.text:
            raise ValueError("text must be a string without NUL")


class OcrPort(Protocol):
    def recognize_pdf(self, content: bytes) -> tuple[OcrPage, ...]: ...
