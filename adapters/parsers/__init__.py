"""Local, bytes-only implementations of the ingestion parser port."""

from adapters.parsers.markdown import MarkdownParser
from adapters.parsers.text import TxtParser

__all__ = ["MarkdownParser", "TxtParser"]
