"""Find OCR in the frozen bundle, on PATH, or in a Windows installation."""

import os
import io
import shutil
import subprocess
import sys
from pathlib import Path


def tesseract_executable() -> Path | None:
    # PyInstaller sets __file__ inside _internal in an onedir build.
    bundled = Path(__file__).resolve().parent / "tesseract" / "tesseract.exe"
    if bundled.is_file():
        return bundled
    installed = shutil.which("tesseract")
    if installed and (sys.platform != "win32" or (Path(installed).parent / "tessdata").is_dir()):
        return Path(installed)
    if sys.platform == "win32":
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidate = Path(root) / "Tesseract-OCR" / "tesseract.exe"
                if candidate.is_file():
                    return candidate
    return Path(installed) if installed else None


def image_to_string(image) -> str:
    import pytesseract

    executable = tesseract_executable()
    if sys.platform != "win32" or not executable:
        return pytesseract.image_to_string(image)
    # Tesseract's Windows CRT mangles non-ASCII environment/argument paths.
    # CreateProcessW can launch it and set a Unicode cwd correctly; relative
    # tessdata and streamed PNG bytes keep all paths out of its narrow argv.
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    result = subprocess.run(
        [str(executable), "stdin", "stdout"],
        cwd=executable.parent,
        env={**os.environ, "TESSDATA_PREFIX": "tessdata"},
        input=payload.getvalue(),
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=120,
    )
    if result.returncode:
        raise pytesseract.TesseractError(result.returncode, result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8", errors="replace")
