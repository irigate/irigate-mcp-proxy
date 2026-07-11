from __future__ import annotations

from pathlib import Path

import pytest

from irigate.workspace import WorkspaceValidationError, resolve_workspace


def test_allows_literal_root_and_descendants(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    workspace = root / "service"
    workspace.mkdir(parents=True)

    assert resolve_workspace(str(root), (str(root),)) == root.resolve()
    assert resolve_workspace(str(workspace), (str(root),)) == workspace.resolve()


def test_star_matches_exactly_one_root_segment(tmp_path: Path) -> None:
    workspace = tmp_path / "team" / "src" / "service"
    workspace.mkdir(parents=True)
    too_deep = tmp_path / "team" / "nested" / "src" / "service"
    too_deep.mkdir(parents=True)
    pattern = f"{tmp_path}/*/src"

    assert resolve_workspace(str(workspace), (pattern,)) == workspace.resolve()
    with pytest.raises(WorkspaceValidationError, match="outside allowed_roots"):
        resolve_workspace(str(too_deep), (pattern,))


def test_double_star_matches_zero_or_more_root_segments(tmp_path: Path) -> None:
    direct = tmp_path / "projects" / "service"
    nested = tmp_path / "teams" / "platform" / "projects" / "service"
    direct.mkdir(parents=True)
    nested.mkdir(parents=True)
    pattern = f"{tmp_path}/**/projects"

    assert resolve_workspace(str(direct), (pattern,)) == direct.resolve()
    assert resolve_workspace(str(nested), (pattern,)) == nested.resolve()


def test_terminal_double_star_allows_root_and_descendants(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    nested = root / "team" / "service"
    nested.mkdir(parents=True)
    pattern = f"{root}/**"

    assert resolve_workspace(str(root), (pattern,)) == root.resolve()
    assert resolve_workspace(str(nested), (pattern,)) == nested.resolve()


@pytest.mark.parametrize("workspace", ["relative/project", "~/project"])
def test_rejects_non_absolute_workspace(workspace: str, tmp_path: Path) -> None:
    with pytest.raises(WorkspaceValidationError, match="absolute path"):
        resolve_workspace(workspace, (str(tmp_path),))


def test_rejects_malformed_absolute_workspace(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceValidationError, match="existing directory"):
        resolve_workspace(f"{tmp_path}/invalid\0workspace", (str(tmp_path),))


def test_rejects_nonexistent_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(WorkspaceValidationError, match="existing directory"):
        resolve_workspace(str(missing), (str(tmp_path),))


def test_rejects_file_workspace(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(WorkspaceValidationError, match="directory"):
        resolve_workspace(str(file_path), (str(tmp_path),))


def test_authorizes_traversal_only_against_canonical_destination(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    child = allowed / "child"
    outside = tmp_path / "outside"
    child.mkdir(parents=True)
    outside.mkdir()
    traversing = child / ".." / ".." / "outside"

    with pytest.raises(WorkspaceValidationError, match="outside allowed_roots"):
        resolve_workspace(str(traversing), (str(allowed),))


def test_rejects_sibling_prefix_confusion(tmp_path: Path) -> None:
    allowed = tmp_path / "project"
    sibling = tmp_path / "project-escape"
    allowed.mkdir()
    sibling.mkdir()

    with pytest.raises(WorkspaceValidationError, match="outside allowed_roots"):
        resolve_workspace(str(sibling), (str(allowed),))


def test_rejects_final_symlink_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    link = allowed / "link"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceValidationError, match="outside allowed_roots"):
        resolve_workspace(str(link), (str(allowed),))


def test_rejects_intermediate_symlink_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    nested = outside / "nested"
    allowed.mkdir()
    nested.mkdir(parents=True)
    (allowed / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceValidationError, match="outside allowed_roots"):
        resolve_workspace(str(allowed / "link" / "nested"), (str(allowed),))


def test_resolves_literal_symlink_prefix_before_matching(tmp_path: Path) -> None:
    target = tmp_path / "target"
    workspace = target / "service"
    workspace.mkdir(parents=True)
    configured_root = tmp_path / "configured-root"
    configured_root.symlink_to(target, target_is_directory=True)

    assert resolve_workspace(str(workspace), (str(configured_root),)) == workspace.resolve()
