"""Initialize the author submodule and apply local patches."""

import subprocess
from pathlib import Path

from qdiscover.catalog import UPSTREAM_COMMIT, UPSTREAM_ROOT


def setup_upstream() -> None:
    """Initialize the pinned submodule and apply documented patches idempotently."""
    project_root = Path(__file__).resolve().parents[2]
    if not (project_root / ".gitmodules").is_file():
        raise RuntimeError("upstream-setup requires a Git checkout of this project")
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive", "--", str(UPSTREAM_ROOT)],
        cwd=project_root,
        check=True,
    )
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=UPSTREAM_ROOT, text=True
    ).strip()
    if commit != UPSTREAM_COMMIT:
        raise RuntimeError(f"Unexpected upstream commit: {commit}; expected {UPSTREAM_COMMIT}")
    for patch in sorted((UPSTREAM_ROOT.parent / "patches").glob("*.patch")):
        apply_upstream_patch(UPSTREAM_ROOT, patch)


def apply_upstream_patch(root: Path, patch: Path) -> None:
    """Accept an already applied patch; reject conflicting source changes."""
    command = ["git", "apply"]
    applied = subprocess.run(
        [*command, "--reverse", "--check", str(patch.resolve())],
        cwd=root,
        capture_output=True,
    )
    if applied.returncode == 0:
        return
    subprocess.run([*command, "--check", str(patch.resolve())], cwd=root, check=True)
    subprocess.run([*command, str(patch.resolve())], cwd=root, check=True)
