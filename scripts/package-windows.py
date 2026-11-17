"""Build and validate a self-contained x64 Windows NSIS installer.

Run after bootstrap: python scripts/package-windows.py
Use --skip-backend only when the current backend was already rebuilt.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def run(*command: str, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--skip-app-build", action="store_true", help="repackage an existing release app after backend-only changes")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Build Windows installers on Windows with the Rust MSVC toolchain")
    # WebView2's generated Rust bindings can exhaust RAM when Cargo uses
    # every logical core on a development laptop. Respect explicit overrides.
    os.environ.setdefault("CARGO_BUILD_JOBS", "2")
    if not args.skip_backend:
        run(sys.executable, str(ROOT / "backend/scripts/build_sidecar.py"))
    executable = ROOT / "app/src-tauri/binaries/sm-backend/sm-backend.exe"
    run(sys.executable, str(ROOT / "scripts/smoke_backend.py"), str(executable))
    run(sys.executable, str(ROOT / "scripts/smoke_sync.py"), str(executable), "--parallel", "2")
    npm = shutil.which("npm")
    if not npm:
        parser.error("Node.js/npm is required")
    run(npm, "ci", cwd=ROOT / "app")
    action = "bundle" if args.skip_app_build else "build"
    run(npm, "run", "tauri", action, "--", "--bundles", "nsis", cwd=ROOT / "app")
    # Check the copied resource too, so an incorrect Tauri resource mapping
    # cannot pass just because the development backend works.
    installed_resource = ROOT / "app/src-tauri/target/release/sm-backend/sm-backend.exe"
    run(sys.executable, str(ROOT / "scripts/smoke_backend.py"), str(installed_resource))
    installers = list((ROOT / "app/src-tauri/target/release/bundle/nsis").glob("*-setup.exe"))
    if not installers:
        raise RuntimeError("Tauri did not produce an NSIS installer")
    for installer in installers:
        print(f"Installer: {installer}")


if __name__ == "__main__":
    main()
