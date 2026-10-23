"""scripts/fetch.py, which the setup scripts run to download the models and llama.cpp. Served from a local
web server here, so nothing is downloaded for real."""
import importlib.util
import io
import tarfile
import threading
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import ROOT

spec = importlib.util.spec_from_file_location("fetch", ROOT / "scripts/fetch.py")
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)
FILE = bytes(range(256)) * 4096  # 1 MB


@pytest.fixture
def server():
    """Serves FILE at /file, and at /broken stops halfway through (a dropped connection)."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(FILE)))
            self.end_headers()
            self.wfile.write(FILE if self.path == "/file" else FILE[:len(FILE) // 2])

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_a_download_arrives_complete(server, tmp_path):
    fetch.download(f"{server}/file", tmp_path / "model.gguf")
    assert (tmp_path / "model.gguf").read_bytes() == FILE


def test_an_interrupted_download_is_never_mistaken_for_a_finished_one(server, tmp_path):
    with pytest.raises(OSError):
        fetch.download(f"{server}/broken", tmp_path / "model.gguf")
    assert not (tmp_path / "model.gguf").exists()

    fetch.download(f"{server}/file", tmp_path / "model.gguf")  # re-running setup finishes the job
    assert (tmp_path / "model.gguf").read_bytes() == FILE


def test_rerunning_setup_downloads_nothing_that_is_already_there(tmp_path, monkeypatch):
    models, bin_ = tmp_path / "models", tmp_path / "bin"
    for path in (models / "parakeet", bin_ / "llama"):
        path.mkdir(parents=True)
    for name in ("silero_vad.onnx", "titanet_small.onnx", "qwen3.5-4b-q4_k_m.gguf", "qwen3.5-9b-q4_k_m.gguf"):
        (models / name).write_bytes(b"x")
    monkeypatch.setattr(fetch, "MODELS", models)
    monkeypatch.setattr(fetch, "BIN", bin_)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail(f"downloaded {a[0]}"))

    fetch.main()


@pytest.mark.parametrize("kind", ["zip", "tar.gz"])
def test_archives_are_unpacked(tmp_path, kind):
    archive = tmp_path / f"llama.{kind}"
    if kind == "zip":
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("build/bin/llama-server", "binary")
    else:
        with tarfile.open(archive, "w:gz") as t:
            info = tarfile.TarInfo("build/bin/llama-server")
            info.size = 6
            t.addfile(info, io.BytesIO(b"binary"))

    fetch.unpack(archive, tmp_path / "out")

    assert (tmp_path / "out/build/bin/llama-server").read_text() == "binary"
