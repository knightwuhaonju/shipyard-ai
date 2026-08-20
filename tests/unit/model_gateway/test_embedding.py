"""Embedding gateway contracts are strict, deterministic, and vendor-neutral."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest

from adapters.embedding import FakeEmbeddingAdapter
from services.model_gateway import (
    EmbeddingAdapterError,
    EmbeddingGateway,
    EmbeddingProfile,
    EmbeddingUnavailableError,
    EmbeddingValidationError,
)


def test_gateway_uses_explicit_profile_and_returns_exact_vectors() -> None:
    profile = EmbeddingProfile(model_id="fake-deterministic-v1", dimension=3)
    adapter = FakeEmbeddingAdapter(profile, {"ballast pump": (1.0, 0.0, 0.0)})

    result = EmbeddingGateway(adapter).embed(("ballast pump",))

    assert result == ((1.0, 0.0, 0.0),)
    assert adapter.calls == (("ballast pump",),)
    assert adapter.profile is profile


def test_profile_dimension_is_configuration_controlled() -> None:
    assert EmbeddingProfile(model_id="model-3", dimension=3).dimension == 3
    assert EmbeddingProfile(model_id="model-8", dimension=8).dimension == 8


class _ModelIdSubclass(str):
    pass


@pytest.mark.parametrize(
    "model_id",
    [
        1,
        _ModelIdSubclass("model"),
        "   ",
        "model\x00id",
        "m" * 129,
    ],
)
def test_profile_rejects_invalid_model_id_without_value_leak(model_id: object) -> None:
    with pytest.raises(EmbeddingValidationError) as captured:
        EmbeddingProfile(model_id=cast(str, model_id), dimension=3)

    assert str(captured.value) == "invalid embedding profile"
    assert "model" not in str(captured.value)


@pytest.mark.parametrize("dimension", [True, 1.0, 0, -1, 2001])
def test_profile_rejects_invalid_dimension(dimension: object) -> None:
    with pytest.raises(EmbeddingValidationError) as captured:
        EmbeddingProfile(model_id="model", dimension=cast(int, dimension))

    assert str(captured.value) == "invalid embedding profile"


def test_profile_is_immutable() -> None:
    profile = EmbeddingProfile(model_id="model", dimension=3)

    with pytest.raises(FrozenInstanceError):
        cast(object, profile).dimension = 8  # type: ignore[attr-defined]


class _RecordingAdapter:
    def __init__(self, profile: EmbeddingProfile, result: object) -> None:
        self.profile = profile
        self._result = result
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        return cast(tuple[tuple[float, ...], ...], self._result)


class _FailingAdapter:
    def __init__(self, profile: EmbeddingProfile) -> None:
        self.profile = profile
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        raise EmbeddingAdapterError("provider secret: hull-77")


@pytest.mark.parametrize(
    "texts",
    [
        ["ballast pump"],
        (),
        tuple("x" for _ in range(129)),
        (1,),
        (_ModelIdSubclass("ballast pump"),),
        ("   ",),
        ("ballast\x00pump",),
        ("x" * 2001,),
    ],
)
def test_gateway_rejects_invalid_input_before_calling_adapter(texts: object) -> None:
    adapter = _RecordingAdapter(
        EmbeddingProfile(model_id="model", dimension=3), ((1.0, 0.0, 0.0),)
    )
    secret = "ballast\x00pump"

    with pytest.raises(EmbeddingValidationError) as captured:
        EmbeddingGateway(adapter).embed(cast(tuple[str, ...], texts))

    assert str(captured.value) == "invalid embedding request"
    assert secret not in str(captured.value)
    assert adapter.calls == []


@pytest.mark.parametrize(
    "result",
    [
        [(1.0, 0.0, 0.0)],
        (),
        ([1.0, 0.0, 0.0],),
        ((1.0, 0.0),),
        ((1, 0.0, 0.0),),
        ((True, 0.0, 0.0),),
        ((float("nan"), 0.0, 0.0),),
        ((float("inf"), 0.0, 0.0),),
        ((-float("inf"), 0.0, 0.0),),
        ((0.0, 0.0, 0.0),),
    ],
)
def test_gateway_translates_invalid_adapter_output(result: object) -> None:
    adapter = _RecordingAdapter(EmbeddingProfile(model_id="model", dimension=3), result)

    with pytest.raises(EmbeddingUnavailableError) as captured:
        EmbeddingGateway(adapter).embed(("ballast pump",))

    assert str(captured.value) == "embedding unavailable"
    assert captured.value.__cause__ is None
    assert adapter.calls == [("ballast pump",)]


def test_gateway_suppresses_typed_adapter_failure_context() -> None:
    adapter = _FailingAdapter(EmbeddingProfile(model_id="model", dimension=3))

    with pytest.raises(EmbeddingUnavailableError) as captured:
        EmbeddingGateway(adapter).embed(("ballast pump",))

    assert str(captured.value) == "embedding unavailable"
    assert "hull-77" not in str(captured.value)
    assert captured.value.__cause__ is None


def test_gateway_does_not_translate_untyped_adapter_exception() -> None:
    class ProgrammingErrorAdapter:
        profile = EmbeddingProfile(model_id="model", dimension=3)

        def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            raise TypeError("programming mistake")

    with pytest.raises(TypeError, match="programming mistake"):
        EmbeddingGateway(ProgrammingErrorAdapter()).embed(("ballast pump",))


def test_fake_copies_vector_mapping_and_raises_typed_error_for_missing_text() -> None:
    profile = EmbeddingProfile(model_id="model", dimension=3)
    vectors = {"ballast pump": (1.0, 0.0, 0.0)}
    adapter = FakeEmbeddingAdapter(profile, vectors)
    vectors["ballast pump"] = (0.0, 1.0, 0.0)

    assert adapter.embed(("ballast pump",)) == ((1.0, 0.0, 0.0),)
    with pytest.raises(EmbeddingAdapterError) as captured:
        adapter.embed(("unknown",))
    assert str(captured.value) == "embedding adapter failed"
    assert captured.value.__cause__ is None


def test_fake_returns_each_batch_in_request_order_deterministically() -> None:
    profile = EmbeddingProfile(model_id="model", dimension=3)
    first_vector = (1.0, 0.0, 0.0)
    second_vector = (0.0, 1.0, 0.0)
    adapter = FakeEmbeddingAdapter(
        profile,
        {"first": first_vector, "second": second_vector},
    )

    assert adapter.embed(("first", "second")) == (first_vector, second_vector)
    assert adapter.embed(("second", "first")) == (second_vector, first_vector)
    assert adapter.embed(("first", "second")) == (first_vector, second_vector)
    assert adapter.calls == (
        ("first", "second"),
        ("second", "first"),
        ("first", "second"),
    )


@pytest.mark.parametrize(
    "vectors",
    [
        {"ballast pump": (1.0, 0.0)},
        {"ballast pump": (1, 0.0, 0.0)},
        {"ballast pump": (float("nan"), 0.0, 0.0)},
        {"ballast pump": (0.0, 0.0, 0.0)},
    ],
)
def test_fake_rejects_invalid_vector_configuration(vectors: object) -> None:
    profile = EmbeddingProfile(model_id="model", dimension=3)

    with pytest.raises(ValueError) as captured:
        FakeEmbeddingAdapter(profile, cast(dict[str, tuple[float, ...]], vectors))

    assert str(captured.value) == "invalid fake embedding configuration"


def _is_allowed_gateway_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return False
    allowed_symbols = {
        "__future__": {"annotations"},
        "dataclasses": {"dataclass"},
        "math": {"isfinite"},
        "typing": {"Protocol"},
    }
    return (
        node.level == 0
        and node.module in allowed_symbols
        and all(
            alias.asname is None and alias.name in allowed_symbols[node.module]
            for alias in node.names
        )
    )


def _is_allowed_fake_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return False
    allowed_symbols = {
        "__future__": {"annotations"},
        "collections.abc": {"Mapping"},
        "services.model_gateway.embedding": {
            "EmbeddingAdapterError",
            "EmbeddingProfile",
        },
    }
    return (
        node.level == 0
        and node.module in allowed_symbols
        and all(
            alias.asname is None and alias.name in allowed_symbols[node.module]
            for alias in node.names
        )
    )


def _source_uses_only_allowed_imports(source: str, *, fake: bool) -> bool:
    checker = _is_allowed_fake_import if fake else _is_allowed_gateway_import
    tree = ast.parse(source)
    top_level_imports = [
        node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    all_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    return len(top_level_imports) == len(all_imports) and all(
        checker(node) for node in all_imports
    )


_ALLOWED_FAKE_DIRECT_CALLS = {
    "EmbeddingAdapterError",
    "ValueError",
    "float",
    "isinstance",
    "len",
    "tuple",
    "type",
}
_ALLOWED_FAKE_METHOD_CALLS = {
    "_valid_entry",
    "append",
    "items",
    "strip",
}


def _fake_source_uses_only_safe_calls(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            if node.func.id not in _ALLOWED_FAKE_DIRECT_CALLS:
                return False
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr not in _ALLOWED_FAKE_METHOD_CALLS:
                return False
        else:
            return False
    return True


@pytest.mark.parametrize(
    ("relative_path", "fake"),
    [
        ("services/model_gateway/embedding.py", False),
        ("adapters/embedding/fake.py", True),
    ],
)
def test_embedding_source_import_boundaries_are_deny_by_default(
    relative_path: str, fake: bool
) -> None:
    source = (Path(__file__).resolve().parents[3] / relative_path).read_text(
        encoding="utf-8"
    )

    assert _source_uses_only_allowed_imports(source, fake=fake)


def test_fake_embedding_call_boundary_is_deny_by_default() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "adapters/embedding/fake.py"
    ).read_text(encoding="utf-8")

    assert _fake_source_uses_only_safe_calls(source)


@pytest.mark.parametrize(
    "malicious_source",
    [
        'open("/tmp/fake-embedding")\n',
        '__import__("socket")\n',
        '__import__("pathlib").Path("/tmp/data").read_text()\n',
        '__import__("socket").create_connection(("127.0.0.1", 1))\n',
        '__import__("subprocess").run(("true",))\n',
        '__import__("os").getenv("SECRET")\n',
        'getattr(__builtins__, "open")("/tmp/fake-embedding")\n',
        'eval("1 + 1")\n',
    ],
)
def test_fake_embedding_call_guard_rejects_dynamic_external_entry_points(
    malicious_source: str,
) -> None:
    assert not _fake_source_uses_only_safe_calls(malicious_source)


@pytest.mark.parametrize(
    ("source", "fake"),
    [
        ("if enabled:\n    from os import environ\n", False),
        ("try:\n    from .. import database\nexcept ImportError:\n    pass\n", False),
        ("from math import isfinite as finite\n", False),
        ("from math import *\n", False),
        ("def hidden():\n    from math import isfinite\n", False),
        ("import requests\n", False),
        ("from services.retrieval import LexicalRetriever\n", False),
        ("from collections.abc import Mapping as Map\n", True),
        ("from .embedding import EmbeddingProfile\n", True),
        (
            "def hidden():\n"
            "    from services.model_gateway.embedding import EmbeddingProfile\n",
            True,
        ),
        ("from sqlalchemy import Engine\n", True),
        ("import socket\n", True),
    ],
)
def test_embedding_import_guard_rejects_nested_and_unapproved_imports(
    source: str, fake: bool
) -> None:
    assert not _source_uses_only_allowed_imports(source, fake=fake)
