from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from irigate.models import UpstreamConfig
from irigate.workspace import WorkspaceValidationError, resolve_workspace

_UPSTREAM_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:/-]*$")
_SELECTOR_NAMES = frozenset({"tools", "upstreams"})
InputBindings = tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


def _workspace_sources(upstream: str, config: UpstreamConfig) -> tuple[str, ...]:
    sources = config.workspace_sources
    if sources == ("workspace",):
        return (f"{upstream}.workspace", "workspace")
    return sources


class SelectionError(ValueError):
    """A safe-to-display downstream selection error."""


@dataclass(frozen=True, slots=True)
class ToolSelection:
    """An exact allowlist of namespaced tools and their required upstreams."""

    tools: frozenset[str]
    upstreams: frozenset[str]
    inputs: InputBindings = ()


@dataclass(frozen=True, slots=True)
class UpstreamSelection:
    """An upstream base set, exclusions, and the resulting selected set."""

    included: frozenset[str]
    excluded: frozenset[str]
    upstreams: frozenset[str]
    inputs: InputBindings = ()


Selection = ToolSelection | UpstreamSelection


def parse_selection(
    query_items: Sequence[tuple[str, str]],
    configured_upstreams: Mapping[str, UpstreamConfig],
) -> Selection:
    """Parse selectors and canonicalized inputs against configured upstreams."""

    items = tuple(query_items)
    configured = frozenset(configured_upstreams)
    selector_items: list[tuple[str, str]] = []
    input_items: list[tuple[str, str]] = []
    configured_sources = {
        source
        for upstream, config in configured_upstreams.items()
        for source in _workspace_sources(upstream, config)
    }
    for name, value in items:
        if name in _SELECTOR_NAMES:
            selector_items.append((name, value))
            continue
        if name not in configured_sources:
            upstream, separator, input_name = name.partition(".")
            if separator and upstream not in configured_upstreams:
                raise SelectionError(f"unknown upstream: {upstream}")
            if separator:
                raise SelectionError(f"unknown input for {upstream}: {input_name}")
            raise SelectionError(f"unsupported query parameter: {name}")
        input_items.append((name, value))

    selected_names = {name for name, _ in selector_items}
    if not selector_items:
        selection: Selection = UpstreamSelection(
            included=configured,
            excluded=frozenset(),
            upstreams=configured,
        )
    elif len(selected_names) != 1:
        raise SelectionError("exactly one selector parameter is required")
    elif len(selector_items) != 1:
        raise SelectionError("repeated selector parameters are not allowed")
    else:
        name, value = selector_items[0]
        if not value:
            raise SelectionError(f"{name} selector must not be empty")
        tokens = value.split(",")
        if any(not token for token in tokens):
            raise SelectionError("empty selector token is not allowed")
        selection = (
            _parse_tools(tokens, configured)
            if name == "tools"
            else _parse_upstreams(tokens, configured)
        )

    return _bind_inputs(
        selection,
        input_items,
        configured_upstreams,
        selector_present=bool(selector_items),
    )


def _bind_inputs(
    selection: Selection,
    input_items: Sequence[tuple[str, str]],
    configured_upstreams: Mapping[str, UpstreamConfig],
    *,
    selector_present: bool,
) -> Selection:
    provided: dict[str, str] = {}
    for source, value in input_items:
        if source in provided:
            raise SelectionError(f"duplicate input: {source}")
        if not value:
            raise SelectionError(f"input must not be empty: {source}")
        provided[source] = value

    if isinstance(selection, ToolSelection):
        explicit_upstreams = selection.upstreams
        excluded = frozenset()
    else:
        explicit_upstreams = selection.included if selector_present else frozenset()
        excluded = selection.excluded

    if provided and (not selector_present or not explicit_upstreams):
        source = sorted(provided)[0]
        raise SelectionError(f"input source requires an explicitly selected upstream: {source}")

    canonical: dict[str, dict[str, str]] = {}
    eligible_sources: set[str] = set()
    for upstream in selection.upstreams:
        upstream_config = configured_upstreams[upstream]
        if not upstream_config.inputs:
            continue
        sources = _workspace_sources(upstream, upstream_config)
        eligible_sources.update(sources)
        source = next((candidate for candidate in sources if candidate in provided), None)
        input_config = upstream_config.inputs["workspace"]
        if source is None:
            if input_config.required:
                raise SelectionError(f"required input is missing: {upstream}.workspace")
            continue
        try:
            resolved = resolve_workspace(provided[source], input_config.allowed_roots)
        except WorkspaceValidationError as exc:
            raise SelectionError(str(exc)) from exc
        canonical[upstream] = {"workspace": str(resolved)}

    unused = sorted(set(provided) - eligible_sources)
    if unused:
        source = unused[0]
        scoped_upstream, separator, _ = source.partition(".")
        if separator and scoped_upstream in excluded:
            raise SelectionError(f"input is for excluded upstream: {scoped_upstream}")
        raise SelectionError(
            f"input source is not used by an explicitly selected upstream: {source}"
        )

    bindings: InputBindings = tuple(
        (upstream, tuple(sorted(values.items())))
        for upstream, values in sorted(canonical.items())
    )
    return replace(selection, inputs=bindings)


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