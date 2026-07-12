from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from irigate.models import UpstreamConfig, WorkspaceInputConfig
from irigate.selection import (
    SelectionError,
    ToolSelection,
    UpstreamSelection,
    parse_selection,
)

UPSTREAMS = {
    key: UpstreamConfig(command="test", idle_timeout_seconds=60)
    for key in ("context7", "code-review-graph", "documentdb", "shadcn")
}


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


def workspace_upstreams(root: Path) -> dict[str, UpstreamConfig]:
    return {
        **UPSTREAMS,
        "filesystem": UpstreamConfig(
            command="test",
            args=("{workspace}",),
            idle_timeout_seconds=60,
            inputs={
                "workspace": WorkspaceInputConfig(
                    type="directory",
                    required=True,
                    allowed_roots=(str(root),),
                )
            },
        ),
    }


def hierarchical_workspace_upstreams(root: Path) -> dict[str, UpstreamConfig]:
    input_config = WorkspaceInputConfig(
        type="directory", required=True, allowed_roots=(str(root),)
    )
    return {
        **UPSTREAMS,
        "filesystem": UpstreamConfig(
            command="test",
            args=("{filesystem.workspace|workspace}",),
            idle_timeout_seconds=60,
            inputs={"workspace": input_config},
        ),
        "git": UpstreamConfig(
            command="test",
            args=("{git.workspace|filesystem.workspace|workspace}",),
            idle_timeout_seconds=60,
            inputs={"workspace": input_config},
        ),
    }


@pytest.mark.parametrize(
    "selector",
    [
        ("upstreams", "filesystem"),
        ("tools", "filesystem__read_file"),
    ],
)
def test_parses_and_canonicalizes_explicit_workspace_input(
    tmp_path: Path, selector: tuple[str, str]
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()

    selection = parse_selection(
        (selector, ("filesystem.workspace", str(workspace / "."))),
        workspace_upstreams(tmp_path),
    )

    assert selection.inputs == (
        ("filesystem", (("workspace", str(workspace.resolve())),)),
    )


def test_reuses_global_workspace_for_selected_upstreams(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()

    selection = parse_selection(
        (("upstreams", "filesystem,git"), ("workspace", str(workspace))),
        hierarchical_workspace_upstreams(tmp_path),
    )

    expected = (("workspace", str(workspace.resolve())),)
    assert selection.inputs == (("filesystem", expected), ("git", expected))


def test_workspace_source_hierarchy_uses_first_provided_value(tmp_path: Path) -> None:
    filesystem_workspace = tmp_path / "filesystem"
    global_workspace = tmp_path / "global"
    filesystem_workspace.mkdir()
    global_workspace.mkdir()

    selection = parse_selection(
        (
            ("upstreams", "git"),
            ("filesystem.workspace", str(filesystem_workspace)),
            ("workspace", str(global_workspace)),
        ),
        hierarchical_workspace_upstreams(tmp_path),
    )

    assert selection.inputs == (
        ("git", (("workspace", str(filesystem_workspace.resolve())),)),
    )


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ((), "required input"),
        ((("filesystem.workspace", "/tmp"),), "explicitly selected"),
        (
            (("upstreams", "!context7"), ("filesystem.workspace", "/tmp")),
            "explicitly selected",
        ),
        (
            (
                ("upstreams", "filesystem,context7,!filesystem"),
                ("filesystem.workspace", "/tmp"),
            ),
            "excluded",
        ),
        ((("upstreams", "filesystem"),), "required input"),
        (
            (
                ("upstreams", "filesystem"),
                ("filesystem.workspace", "/tmp"),
                ("filesystem.workspace", "/tmp"),
            ),
            "duplicate input",
        ),
        (
            (("upstreams", "filesystem"), ("filesystem.root", "/tmp")),
            "unknown input",
        ),
        (
            (("upstreams", "context7"), ("missing.workspace", "/tmp")),
            "unknown upstream",
        ),
        (
            (("upstreams", "context7"), ("filesystem.workspace", "/tmp")),
            "explicitly selected",
        ),
        (
            (("upstreams", "filesystem"), ("filesystem.workspace", "relative")),
            "absolute path",
        ),
        (
            (("upstreams", "filesystem"), ("filesystem.workspace", "")),
            "must not be empty",
        ),
    ],
)
def test_rejects_invalid_workspace_inputs(
    tmp_path: Path,
    items: Sequence[tuple[str, str]],
    message: str,
) -> None:
    with pytest.raises(SelectionError, match=message):
        parse_selection(items, workspace_upstreams(tmp_path))


def test_rejects_workspace_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    with pytest.raises(SelectionError, match="outside allowed_roots"):
        parse_selection(
            (
                ("upstreams", "filesystem"),
                ("filesystem.workspace", str(outside)),
            ),
            workspace_upstreams(allowed),
        )
