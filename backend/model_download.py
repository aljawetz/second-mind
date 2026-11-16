"""Downloads the embedding model for the plugin (plan
docs/plans/2026-11-13-claude-code-plugin.md: the student installs nothing by
hand, so the plugin fetches the model itself).

Only bge-small-en-v1.5, straight from Hugging Face's own ONNX export, pinned
to one revision and checked by sha256. Its vectors match the app's
optimum-exported model (scripts/convert_embedding_model.py) to 1e-7, so an
index either one built works with the other. The plugin has no reranker.

Each file downloads to a .part file and is renamed only after its hash
checks out, so a cut connection never leaves a half model behind. A file
already there is kept as is: the repo's dev models (a different export of
the same weights) stay untouched.
"""

import hashlib
import sys
from pathlib import Path
from typing import Callable

import httpx

import embeddings

REPO = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
# local name: (path in the repo, sha256)
FILES = {
    "model.onnx": ("onnx/model.onnx", "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35"),
    "tokenizer.json": ("tokenizer.json", "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"),
}
CHUNK = 1 << 20


class ModelDownloadError(RuntimeError):
    pass


def url_for(repo_path: str) -> str:
    return f"https://huggingface.co/{REPO}/resolve/{REVISION}/{repo_path}"


def model_ready(model_dir: Path = embeddings.MODEL_DIR) -> bool:
    return all((model_dir / name).is_file() for name in FILES)


def ensure_embedding_model(
    model_dir: Path = embeddings.MODEL_DIR,
    client: httpx.Client | None = None,
    progress: Callable[[str, int, int | None], None] | None = None,
) -> Path:
    """Downloads whatever model file is missing. progress(name, done, total)
    is called as bytes arrive. Raises ModelDownloadError on a network error
    or a hash mismatch."""
    missing = [name for name in FILES if not (model_dir / name).is_file()]
    if not missing:
        return model_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=60.0))
    try:
        for name in missing:
            _download(client, name, model_dir, progress)
    finally:
        if own:
            client.close()
    return model_dir


def _download(client: httpx.Client, name: str, model_dir: Path, progress) -> None:
    repo_path, sha256 = FILES[name]
    part = model_dir / f"{name}.part"
    digest = hashlib.sha256()
    try:
        with client.stream("GET", url_for(repo_path)) as response:
            response.raise_for_status()
            total = int(response.headers["content-length"]) if "content-length" in response.headers else None
            done = 0
            with open(part, "wb") as f:
                for chunk in response.iter_bytes(CHUNK):
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(name, done, total)
    except httpx.HTTPError as e:
        part.unlink(missing_ok=True)
        raise ModelDownloadError(f"Could not download {name} from Hugging Face: {e}") from e
    if digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise ModelDownloadError(f"{name} from Hugging Face did not match its expected hash; nothing was saved.")
    part.replace(model_dir / name)


def _print_progress(name: str, done: int, total: int | None) -> None:
    """One line per 25 MB, not a redrawn bar: the setup skill reads this
    through Claude's Bash tool, where every redraw would be a line."""
    step = 25_000_000
    if done != total and done // step == (done - CHUNK) // step:
        return
    line = f"{name}: {done / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else "")
    print(line, file=sys.stderr, flush=True)


def main() -> None:
    """sm-mcp --download-model: what /second-mind:setup runs."""
    if model_ready():
        print(f"Embedding model already in {embeddings.MODEL_DIR}", file=sys.stderr)
        return
    try:
        path = ensure_embedding_model(progress=_print_progress)
    except ModelDownloadError as e:
        print(e, file=sys.stderr)
        raise SystemExit(1)
    print(f"Embedding model ready in {path}", file=sys.stderr)
