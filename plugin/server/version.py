"""The package version for hatchling (pyproject.toml [tool.hatch.version]):
the release number plus a short hash of the backend code it ships, so every
code change is a new version and uvx builds a fresh env for it."""

import hashlib
from pathlib import Path

RELEASE = "0.1.0"

_backend = Path(__file__).resolve().parent.parent.parent / "backend"
_digest = hashlib.sha256()
for _path in sorted(_backend.glob("*.py")):
    _digest.update(_path.name.encode() + b"\0" + _path.read_bytes())
__version__ = f"{RELEASE}+{_digest.hexdigest()[:10]}"
