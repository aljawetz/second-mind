"""Sign out and delete everything Second Mind keeps about the student.

Sprint 8 responsible deployment: a student must be able to remove their
data. This wipes the whole data folder (course index, synced files,
conversations, memory, study sets, settings) and forgets every stored
credential. It does not touch Canvas, OpenAI or any other service, and a
copy the student already exported or a provider already received stays
where it is."""

import shutil
from pathlib import Path

import credentials

CREDENTIAL_KEYS = ("canvas-token", "openai-key", "deepseek-key", "github-copilot-token")


def delete_all_data(sm_home: Path) -> dict:
    removed = 0
    if sm_home.is_dir():
        for child in sm_home.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
    for key in CREDENTIAL_KEYS:
        credentials.delete(key)
    return {"status": "deleted", "items_removed": removed, "credentials_forgotten": list(CREDENTIAL_KEYS)}
