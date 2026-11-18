import native_tools


def test_finds_windows_installation_without_path(tmp_path, monkeypatch):
    executable = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    executable.parent.mkdir()
    executable.touch()
    monkeypatch.setattr(native_tools.sys, "platform", "win32")
    monkeypatch.setattr(native_tools.shutil, "which", lambda _: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert native_tools.tesseract_executable() == executable


def test_bundled_ocr_wins_over_system_installation(tmp_path, monkeypatch):
    executable = tmp_path / "tesseract" / "tesseract.exe"
    executable.parent.mkdir()
    executable.touch()
    monkeypatch.setattr(native_tools, "__file__", str(tmp_path / "native_tools.py"))
    monkeypatch.setattr(native_tools.shutil, "which", lambda _: "unrelated/tesseract.exe")
    monkeypatch.setenv("TESSDATA_PREFIX", "unrelated-language-data")
    assert native_tools.tesseract_executable() == executable
    assert native_tools.os.environ["TESSDATA_PREFIX"] == "unrelated-language-data"


def test_windows_ocr_streams_input_and_uses_relative_data(tmp_path, monkeypatch):
    from PIL import Image
    from types import SimpleNamespace

    executable = tmp_path / "日本語" / "tesseract.exe"
    monkeypatch.setattr(native_tools.sys, "platform", "win32")
    monkeypatch.setattr(native_tools, "tesseract_executable", lambda: executable)
    monkeypatch.setattr(native_tools.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"Course material", stderr=b"")

    monkeypatch.setattr(native_tools.subprocess, "run", run)
    assert native_tools.image_to_string(Image.new("RGB", (10, 10))) == "Course material"
    command, kwargs = calls[0]
    assert command == [str(executable), "stdin", "stdout"]
    assert kwargs["cwd"] == executable.parent
    assert kwargs["env"]["TESSDATA_PREFIX"] == "tessdata"
    assert kwargs["input"].startswith(b"\x89PNG")
