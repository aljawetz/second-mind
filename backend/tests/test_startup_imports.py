"""main._load_heavy_modules: the first requests at launch (sync, the
assignments list, sessions, study, the startup memory jobs) used to import
llama_index each in its own thread, and Python's import machinery broke
under that: "cannot import name 'BaseRetriever' from partially initialized
module" and "_DeadlockError", so 18-658's sync failed before starting
(seen in the app, 2026-11-17). The heavy modules are now imported once,
under a lock."""

import threading
import time

import main


def test_heavy_modules_are_imported_once_even_when_many_threads_ask_at_once(monkeypatch):
    imported = []

    def slow_import(name):
        imported.append(name)
        time.sleep(0.01)  # widens the window two threads could both get through

    monkeypatch.setattr(main, "_heavy_loaded", False)
    monkeypatch.setattr(main.importlib, "import_module", slow_import)
    threads = [threading.Thread(target=main._load_heavy_modules) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert imported == list(main.HEAVY_MODULES)


def test_light_routes_dont_wait_for_the_heavy_imports():
    assert main._needs_heavy_modules("/ping") is False
    assert main._needs_heavy_modules("/config") is False
    assert main._needs_heavy_modules("/credentials/status") is False
    assert main._needs_heavy_modules("/courses/55016/sync") is True
    assert main._needs_heavy_modules("/courses/55016/assignments") is True


def test_the_heavy_module_list_names_real_modules():
    import importlib

    for name in main.HEAVY_MODULES:
        importlib.import_module(name)
