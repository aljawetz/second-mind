"""Install a built sidecar without deleting a running Windows app's resources."""

from pathlib import Path
import shutil
import sys
import tempfile


def install_sidecar(source: Path, dest: Path, workspace: Path) -> None:
    source, dest, workspace = source.resolve(), dest.resolve(), workspace.resolve()
    if not source.is_relative_to(workspace) or not dest.is_relative_to(workspace):
        raise ValueError("Sidecar installation paths must stay inside the workspace")
    executable = dest / "sm-backend.exe"
    if sys.platform == "win32" and executable.exists():
        try:
            with executable.open("r+b"):
                pass
        except PermissionError as error:
            raise RuntimeError("Close Second Mind and stop npm run tauri dev before replacing the backend. The new build is ready in backend/dist/sm-backend.") from error
    staging_root = workspace / "backend" / "build"
    staging_root.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-sidecar-", dir=staging_root) as directory:
        previous = Path(directory) / "previous"
        if not previous.resolve().is_relative_to(workspace):
            raise ValueError("Sidecar staging paths must stay inside the workspace")
        if dest.exists():
            dest.rename(previous)
        try:
            shutil.copytree(source, dest, symlinks=True)
        except OSError:
            if dest.exists():
                shutil.rmtree(dest)
            if previous.exists():
                previous.rename(dest)
            raise
