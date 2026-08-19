"""Shared framework-independent information-security levels."""

from enum import IntEnum


class SecurityLevel(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3
