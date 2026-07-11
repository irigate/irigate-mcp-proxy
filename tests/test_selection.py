from __future__ import annotations

from collections.abc import Sequence

import pytest

from irigate.selection import (
    SelectionError,
    ToolSelection,
    UpstreamSelection,
    parse_selection,
)

UPSTREAMS = ("context7", "code-review-graph", "documentdb", "shadcn")


def parse(*items: tuple[str, str]):
    return parse_selection(items, UPSTREAMS)


def test_parses_exact_tool_selection() -> None:
    selection = parse(
        (
            "tools",
            "context7__resolve-library-id,context7__query-docs,shadcn__search-items",
        )
    )

    assert selection == ToolSelection(
        tools=frozenset(
            {
                "context7__resolve-library-id",
                "context7__query-docs",
                "shadcn__search-items",
            }
        ),
        upstreams=frozenset({"context7", "shadcn"}),
    )


def test_normalizes_duplicate_exact_tools() -> None:
    selection = parse(("tools", "context7__query-docs,context7__query-docs"))

    assert selection.tools == frozenset({"context7__query-docs"})
    assert selection.upstreams == frozenset({"context7"})


def test_parses_positive_upstream_selection() -> None:
    selection = parse(("upstreams", "context7,shadcn"))

    assert selection == UpstreamSelection(
        included=frozenset({"context7", "shadcn"}),
        excluded=frozenset(),
        upstreams=frozenset({"context7", "shadcn"}),
    )


def test_missing_selector_selects_all_configured_upstreams() -> None:
    selection = parse()

    assert selection == UpstreamSelection(
        included=frozenset(UPSTREAMS),
        excluded=frozenset(),
        upstreams=frozenset(UPSTREAMS),
    )


def test_reverse_only_selection_uses_all_upstreams_as_base() -> None:
    selection = parse(("upstreams", "!code-review-graph,!documentdb"))

    assert selection == UpstreamSelection(
        included=frozenset(),
        excluded=frozenset({"code-review-graph", "documentdb"}),
        upstreams=frozenset({"context7", "shadcn"}),
    )


@pytest.mark.parametrize(
    "value",
    [
        "context7,shadcn,!shadcn",
        "!shadcn,context7,shadcn",
    ],
)
def test_mixed_selection_uses_positive_base_and_exclusion_wins(value: str) -> None:
    selection = parse(("upstreams", value))

    assert selection.included == frozenset({"context7", "shadcn"})
    assert selection.excluded == frozenset({"shadcn"})
    assert selection.upstreams == frozenset({"context7"})


def test_normalizes_duplicate_upstream_tokens() -> None:
    selection = parse(
        ("upstreams", "context7,context7,shadcn,!shadcn,!shadcn")
    )

    assert selection.included == frozenset({"context7", "shadcn"})
    assert selection.excluded == frozenset({"shadcn"})
    assert selection.upstreams == frozenset({"context7"})


@pytest.mark.parametrize(
    ("items", "message"),
    [
        (
            (("tools", "context7__query-docs"), ("upstreams", "context7")),
            "exactly one selector",
        ),
        (
            (("tools", "context7__query-docs"), ("tools", "context7__resolve")),
            "repeated selector",
        ),
        (
            (("upstreams", "context7"), ("upstreams", "shadcn")),
            "repeated selector",
        ),
        ((("unknown", "context7"),), "unsupported query parameter"),
        ((("tools", ""),), "must not be empty"),
        ((("tools", "context7__query-docs,"),), "empty selector token"),
        ((("upstreams", "context7,,shadcn"),), "empty selector token"),
        ((("tools", "!context7__query-docs"),), "invalid tool selector"),
        ((("tools", "context7"),), "invalid tool selector"),
        ((("tools", "context7__bad tool"),), "invalid tool selector"),
        ((("tools", "missing__query-docs"),), "unknown upstream"),
        ((("upstreams", "Context7"),), "invalid upstream selector"),
        ((("upstreams", "missing"),), "unknown upstream"),
        ((("upstreams", "!missing"),), "unknown upstream"),
        ((("upstreams", "context7,!context7"),), "must select at least one upstream"),
    ],
)
def test_rejects_invalid_selection(
    items: Sequence[tuple[str, str]], message: str
) -> None:
    with pytest.raises(SelectionError, match=message):
        parse(*items)
