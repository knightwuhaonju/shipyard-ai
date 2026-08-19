"""Deterministic byte fixtures for document parser adapter tests."""


def synthetic_txt_bytes() -> bytes:
    """Return UTF-8 BOM-prefixed synthetic plain text."""
    return "\ufeff合成船厂规范\r\n\r\n泵组检查。\r\n第二行。".encode("utf-8")


def synthetic_markdown_bytes() -> bytes:
    """Return synthetic Markdown with headings, prose, and a table."""
    return (
        "# 合成规范\n\n"
        "## 泵组\n\n"
        "检查轴封。\n\n"
        "| 项目 | 数量 |\n| --- | ---: |\n| 泵 | 2 |\n"
    ).encode()
