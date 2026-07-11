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
    input_items: list[tuple[str, str, str]] = []
    for name, value in items:
        if name in _SELECTOR_NAMES:
            selector_items.append((name, value))
            continue
        upstream, separator, input_name = name.partition(".")
        if not separator:
            raise SelectionError(f"unsupported query parameter: {name}")
        if upstream not in configured_upstreams:
            raise SelectionError(f"unknown upstream: {upstream}")
        if input_name not in configured_upstreams[upstream].inputs:
            raise SelectionError(f"unknown input for {upstream}: {input_name}")
        input_items.append((upstream, input_name, value))

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
    input_items: Sequence[tuple[str, str, str]],
    configured_upstreams: Mapping[str, UpstreamConfig],
    *,
    selector_present: bool,
) -> Selection:
    provided: dict[str, dict[str, str]] = {}
    for upstream, input_name, value in input_items:
        upstream_values = provided.setdefault(upstream, {})
        if input_name in upstream_values:
            raise SelectionError(f"duplicate input: {upstream}.{input_name}")
        upstream_values[input_name] = value

    if isinstance(selection, ToolSelection):
        explicit_upstreams = selection.upstreams
        excluded = frozenset()
    else:
        explicit_upstreams = selection.included if selector_present else frozenset()
        excluded = selection.excluded

    canonical: dict[str, dict[str, str]] = {}
    for upstream, values in provided.items():
        if upstream in excluded:
            raise SelectionError(f"input is for excluded upstream: {upstream}")
        if upstream not in explicit_upstreams:
            raise SelectionError(
                f"input upstream must be explicitly selected: {upstream}"
            )
        for input_name, value in values.items():
            if not value:
                raise SelectionError(f"input must not be empty: {upstream}.{input_name}")
            input_config = configured_upstreams[upstream].inputs[input_name]
            try:
                resolved = resolve_workspace(value, input_config.allowed_roots)
            except WorkspaceValidationError as exc:
                raise SelectionError(str(exc)) from exc
            canonical.setdefault(upstream, {})[input_name] = str(resolved)

    for upstream in selection.upstreams:
        for input_name, input_config in configured_upstreams[upstream].inputs.items():
            if input_config.required and input_name not in provided.get(upstream, {}):
                raise SelectionError(f"required input is missing: {upstream}.{input_name}")

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