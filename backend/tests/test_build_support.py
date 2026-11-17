import pytest
import build_support

from build_support import install_sidecar


def test_installs_complete_backend_and_preserves_build_output(tmp_path):
    source = tmp_path / "backend/dist/sm-backend"
    source.mkdir(parents=True)
    (source / "model").write_text("new")
    dest = tmp_path / "app/binaries/sm-backend"
    dest.mkdir(parents=True)
    (dest / "model").write_text("old")
    install_sidecar(source, dest, tmp_path)
    assert (dest / "model").read_text() == "new"
    assert (source / "model").read_text() == "new"


def test_failed_replacement_restores_previous_backend(tmp_path, monkeypatch):
    source = tmp_path / "backend/dist/sm-backend"
    source.mkdir(parents=True)
    (source / "model").write_text("new")
    dest = tmp_path / "app/binaries/sm-backend"
    dest.mkdir(parents=True)
    (dest / "model").write_text("old")
    def failed_copy(source, target, **kwargs):
        target.mkdir()
        (target / "partial").write_text("incomplete")
        raise PermissionError("locked")

    monkeypatch.setattr(build_support.shutil, "copytree", failed_copy)
    with pytest.raises(PermissionError):
        install_sidecar(source, dest, tmp_path)
    assert (dest / "model").read_text() == "old"
    assert not (dest / "partial").exists()
