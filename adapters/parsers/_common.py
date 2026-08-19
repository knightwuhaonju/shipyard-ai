"""Security preflight shared by ZIP-based OOXML parser adapters."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, LargeZipFile, ZipFile

import services.ingestion.parser as parser_contract
from services.ingestion import ParserError, ParserErrorCode

_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:/")


def validate_ooxml_archive(content: bytes) -> None:
    """Validate OOXML ZIP member metadata without extracting any content."""
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
    except (BadZipFile, LargeZipFile) as error:
        raise ParserError(ParserErrorCode.INVALID_DOCUMENT) from error

    if len(members) > parser_contract.MAX_ARCHIVE_ENTRIES:
        raise ParserError(ParserErrorCode.RESOURCE_LIMIT)

    normalized_names: set[str] = set()
    uncompressed_total = 0
    for member in members:
        normalized_name = member.filename.replace("\\", "/")
        path = PurePosixPath(normalized_name)
        if (
            not normalized_name
            or normalized_name in normalized_names
            or path.is_absolute()
            or _WINDOWS_ABSOLUTE_PATH.match(normalized_name) is not None
            or ".." in path.parts
        ):
            raise ParserError(ParserErrorCode.INVALID_DOCUMENT)
        normalized_names.add(normalized_name)

        uncompressed_total += member.file_size
        if uncompressed_total > parser_contract.MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)

        if normalized_name.endswith("/") or member.file_size == 0:
            continue
        if (
            member.compress_size == 0
            or member.file_size
            > parser_contract.MAX_ARCHIVE_COMPRESSION_RATIO * member.compress_size
        ):
            raise ParserError(ParserErrorCode.RESOURCE_LIMIT)
