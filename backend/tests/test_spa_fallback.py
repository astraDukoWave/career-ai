"""Reloading a client-side route serves the SPA instead of a 404."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import SPAStaticFiles


def _client(tmp_path) -> TestClient:
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    app.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True), name="static")
    return TestClient(app)


def test_client_routes_serve_index_html(tmp_path):
    client = _client(tmp_path)
    for path in ("/", "/cv", "/interview"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert '<div id="root">' in res.text


def test_real_files_and_misses_keep_their_status(tmp_path):
    client = _client(tmp_path)
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/unknown").status_code == 404
    assert client.get("/api/ping").json() == {"ok": True}
