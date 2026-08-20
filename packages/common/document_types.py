"""Approved immutable source-document formats."""

from enum import StrEnum

__all__ = ["DocumentType"]


class DocumentType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    TXT = "txt"
    MARKDOWN = "markdown"
