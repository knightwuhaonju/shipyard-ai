"""Local, bytes-only implementations of the ingestion parser port."""

from adapters.parsers.docx import DocxParser
from adapters.parsers.markdown import MarkdownParser
from adapters.parsers.text import TxtParser
from adapters.parsers.xlsx import XlsxParser

__all__ = ["DocxParser", "MarkdownParser", "TxtParser", "XlsxParser"]
