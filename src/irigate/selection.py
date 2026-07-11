from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_UPSTREAM_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:/-]*$")
_SELECTOR_NAMES = frozenset({"tools", "upstreams"})


class SelectionError(ValueError):
    """A safe-to-display downstream selection error."""


@dataclass(frozen=True, slots=True)
class ToolSelection:
    """An exact allowlist of namespaced tools and their required upstreams."""

    tools: frozenset[str]
    upstreams: frozenset[str]


@dataclass(frozen=True, slots=True)
class UpstreamSelection:
    """An upstream base set, exclusions, and the resulting selected set."""

    included: frozenset[str]
    excluded: frozenset[str]
    upstreams: frozenset[str]


Selection = ToolSelection | UpstreamSelection


def parse_selection(
    query_items: Sequence[tuple[str, str]],
    configured_upstreams: Iterable[str],
) -> Selection:
    """Parse one decoded query-string selector against configured upstream keys."""

    items = tuple(query_items)
    configured = frozenset(configured_upstreams)
    unsupported = sorted({name for name, _ in items if name not in _SELECTOR_NAMES})
    if unsupported:
        raise SelectionError("unsupported query parameter: " + ", ".join(unsupported))

    selector_items = [(name, value) for name, value in items if name in _SELECTOR_NAMES]
    selected_names = {name for name, _ in selector_items}
    if not selector_items:
        return UpstreamSelection(
            included=configured,
            excluded=frozenset(),
            upstreams=configured,
        )
    if len(selected_names) != 1:
        raise SelectionError("exactly one selector parameter is required")
    if len(selector_items) != 1:
        raise SelectionError("repeated selector parameters are not allowed")

    name, value = selector_items[0]
    if not value:
        raise SelectionError(f"{name} selector must not be empty")
    tokens = value.split(",")
    if any(not token for token in tokens):
        raise SelectionError("empty selector token is not allowed")

    if name == "tools":
        return _parse_tools(tokens, configured)
    return _parse_upstreams(tokens, configured)


def _parse_tools(tokens: Sequence[str], configured: frozenset[str]) -> ToolSelection:
    tools: set[str] = set()
    upstreams: set[str] = set()
    for token in tokens:
        upstream, separator, tool = token.partition("__")
        if (
            not separator
            or _UPSTREAM_NAME.fullmatch(upstream) is None
            or _TOOL_NAME.fullmatch(tool) is None
        ):
            raise SelectionError(f"invalid tool selector: {token}")
        if upstream not in configured:
            raise SelectionError(f"unknown upstream: {upstream}")
        tools.add(token)
        upstreams.add(upstream)
    return ToolSelection(tools=frozenset(tools), upstreams=frozenset(upstreams))


def _parse_upstreams(
    tokens: Sequence[str], configured: frozenset[str]
) -> UpstreamSelection:
    included: set[str] = set()
    excluded: set[str] = set()
    for token in tokens:
        reverse = token.startswith("!")
        upstream = token[1:] if reverse else token
        if _UPSTREAM_NAME.fullmatch(upstream) is None:
            raise SelectionError(f"invalid upstream selector: {token}")
        if upstream not in configured:
            raise SelectionError(f"unknown upstream: {upstream}")
        (excluded if reverse else included).add(upstream)

    base = included if included else set(configured)
    selected = base - excluded
    if not selected:
        raise SelectionError("selection must select at least one upstream")
    return UpstreamSelection(
        included=frozenset(included),
        excluded=frozenset(excluded),
        upstreams=frozenset(selected),
    )