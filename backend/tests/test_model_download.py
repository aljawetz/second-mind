"""model_download: the plugin fetches bge-small from Hugging Face itself,
pinned and hash-checked, so the student downloads nothing by hand."""

import hashlib

import httpx
import pytest

import model_download

BODIES = {"onnx/model.onnx": b"onnx-bytes" * 1000, "tokenizer.json": b'{"tok": 1}'}


@pytest.fixture
def pinned(monkeypatch):
    """Point FILES at the fake bodies' hashes, keeping the real repo paths."""
    files = {name: (path, hashlib.sha256(BODIES[path]).hexdigest()) for name, (path, _) in model_download.FILES.items()}
    monkeypatch.setattr(model_download, "FILES", files)
    return files


def _client(bodies, requests):
    def handler(request):
        requests.append(str(request.url))
        path = request.url.path.split(f"/resolve/{model_download.REVISION}/", 1)[1]
        if path not in bodies:
            return httpx.Response(404)
        return httpx.Response(200, content=bodies[path], headers={"content-length": str(len(bodies[path]))})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_downloads_the_pinned_revision_and_reports_progress(tmp_path, pinned):
    requests, seen = [], []

    out = model_download.ensure_embedding_model(tmp_path / "m", _client(BODIES, requests), lambda *a: seen.append(a))

    assert (out / "model.onnx").read_bytes() == BODIES["onnx/model.onnx"]
    assert (out / "tokenizer.json").read_bytes() == BODIES["tokenizer.json"]
    assert all(f"huggingface.co/BAAI/bge-small-en-v1.5/resolve/{model_download.REVISION}/" in r for r in requests)
    assert seen[-1] == ("tokenizer.json", len(BODIES["tokenizer.json"]), len(BODIES["tokenizer.json"]))
    assert model_download.model_ready(out)
    assert not list(out.glob("*.part"))


def test_files_already_there_are_kept(tmp_path, pinned):
    (tmp_path / "model.onnx").write_bytes(b"the repo's own export")
    requests = []

    model_download.ensure_embedding_model(tmp_path, _client(BODIES, requests))

    assert (tmp_path / "model.onnx").read_bytes() == b"the repo's own export"
    assert [r.rsplit("/", 1)[1] for r in requests] == ["tokenizer.json"]


def test_a_hash_mismatch_saves_nothing(tmp_path, pinned):
    bad = {**BODIES, "onnx/model.onnx": b"tampered"}

    with pytest.raises(model_download.ModelDownloadError, match="hash"):
        model_download.ensure_embedding_model(tmp_path, _client(bad, []))

    assert not (tmp_path / "model.onnx").exists()
    assert not list(tmp_path.glob("*.part"))


def test_a_network_error_says_so_and_cleans_up(tmp_path, pinned):
    with pytest.raises(model_download.ModelDownloadError, match="Hugging Face"):
        model_download.ensure_embedding_model(tmp_path, _client({}, []))

    assert not list(tmp_path.iterdir())

