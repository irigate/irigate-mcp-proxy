from __future__ import annotations

from functools import lru_cache
from pathlib import Path


class WorkspaceValidationError(ValueError):
    """A safe-to-display workspace authorization failure."""


def resolve_workspace(workspace: str, allowed_roots: tuple[str, ...]) -> Path:
    """Resolve and authorize one workspace against path-segment root patterns."""

    requested = Path(workspace)
    if not requested.is_absolute():
        raise WorkspaceValidationError("workspace must be an explicit absolute path")
    try:
        canonical = requested.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkspaceValidationError(
            f"workspace is not an existing directory: {workspace}"
        ) from exc
    if not canonical.is_dir():
        raise WorkspaceValidationError(f"workspace is not a directory: {workspace}")

    candidate_parts = canonical.parts[1:]
    for pattern in allowed_roots:
        pattern_parts = _canonical_pattern_parts(pattern)
        if _matches_allowed_root(pattern_parts, candidate_parts):
            return canonical
    raise WorkspaceValidationError(f"workspace is outside allowed_roots: {workspace}")


def _canonical_pattern_parts(pattern: str) -> tuple[str, ...]:
    parts = tuple(segment for segment in pattern.split("/") if segment)
    wildcard_index = next(
        (index for index, segment in enumerate(parts) if segment in {"*", "**"}),
        len(parts),
    )
    literal_prefix = Path("/", *parts[:wildcard_index])
    try:
        canonical_prefix = literal_prefix.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkspaceValidationError(
            f"allowed_roots literal prefix does not exist: {literal_prefix}"
        ) from exc
    if not canonical_prefix.is_dir():
        raise WorkspaceValidationError(
            f"allowed_roots literal prefix is not a directory: {literal_prefix}"
        )
    return canonical_prefix.parts[1:] + parts[wildcard_index:]


def _matches_allowed_root(
    pattern_parts: tuple[str, ...], candidate_parts: tuple[str, ...]
) -> bool:
    @lru_cache(maxsize=None)
    def match(pattern_index: int, candidate_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return True

        segment = pattern_parts[pattern_index]
        if segment == "**":
            return match(pattern_index + 1, candidate_index) or (
                candidate_index < len(candidate_parts)
                and match(pattern_index, candidate_index + 1)
            )
        if candidate_index == len(candidate_parts):
            return False
        if segment == "*" or segment == candidate_parts[candidate_index]:
            return match(pattern_index + 1, candidate_index + 1)
        return False

    return match(0, 0)
