"""Sign out and delete all data (Sprint 8 responsible deployment)."""

import http.client
import json
import threading

import credentials
import privacy


def test_delete_all_data_empties_the_folder_and_forgets_credentials(tmp_path, monkeypatch):
    (tmp_path / "index.lancedb").mkdir()
    (tmp_path / "index.lancedb" / "t.lance").write_text("x")
    (tmp_path / "courses").mkdir()
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "memory.db").write_text("m")
    forgotten = []
    monkeypatch.setattr(credentials, "delete", forgotten.append)

    result = privacy.delete_all_data(tmp_path)

    assert list(tmp_path.iterdir()) == []
    assert result["items_removed"] == 4
    assert set(forgotten) == set(privacy.CREDENTIAL_KEYS) == set(result["credentials_forgotten"])


def test_delete_all_data_with_nothing_there_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "delete", lambda key: None)
    assert privacy.delete_all_data(tmp_path / "missing")["items_removed"] == 0


def test_in_app_delete_drops_the_in_memory_copy(monkeypatch):
    monkeypatch.setenv(credentials.FROM_APP_ENV, "1")
    credentials.receive(b'{"canvas-token": "t"}')
    assert credentials.get("canvas-token") == "t"
    credentials.delete("canvas-token")
    assert credentials.get("canvas-token") is None


def test_delete_data_endpoint(tmp_path, monkeypatch):
    import main

    (tmp_path / "config.json").write_text("{}")
    monkeypatch.setattr(main, "SM_HOME", tmp_path)
    monkeypatch.setattr(credentials, "delete", lambda key: None)
    server = main.ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("DELETE", "/data")
        response = conn.getresponse()
        assert response.status == 400
        assert json.loads(response.read())["error"]["code"] == "confirmation_required"
        assert (tmp_path / "config.json").exists()
        conn.request("DELETE", "/data?confirm=delete-all-my-data")
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["status"] == "deleted"
        assert list(tmp_path.iterdir()) == []
    finally:
        server.shutdown()
        server.server_close()
