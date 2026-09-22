"""ESP3D client against a tiny local stand-in for the ESP32's HTTP server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from foamcut.esp import Esp3d, EspError, parse_job

PROGRAM = """; foamcut wing: clarky.dat 100 -> clarky.dat 80, Panel 400
; foamcut-job block=124x36x410 x=20 y=31 root=T2 s=465 time=2.8min travel=X0..134,Y0..55,U0..134,V0..58
; Schnittzeit ca. 2.8 min, 119 Stuetzpunkte
G21
M2
"""


class FakeEsp3d(BaseHTTPRequestHandler):
    files = {"fluegel.nc": PROGRAM, "index.html.gz": "x"}
    commands: list[str] = []
    uploads: list[bytes] = []

    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="application/json"):
        self.send_response(200); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/files?"):
            self._send(json.dumps({"files": [{"name": n, "size": f"{len(b)} B", "time": ""} for n, b in self.files.items()],
                                   "path": "/", "total": "1 MB", "used": "10 KB", "occupation": 1}).encode())
        elif self.path.startswith("/command?cmd="):
            cmd = self.path[len("/command?cmd="):]
            from urllib.parse import unquote
            self.commands.append(unquote(cmd))
            if "[ESP701]" in cmd:
                self._send(json.dumps({"cmd": "701", "status": "ok", "data": {"status": "processing", "total": "100",
                                                                                "processed": "40", "name": "/FS/fluegel.nc"}}).encode())
            else:
                self._send(b'{"cmd":"700","status":"ok","data":"Processing /fluegel.nc"}')
        else:
            name = self.path.lstrip("/")
            if name in self.files:
                self._send(self.files[name].encode(), "text/plain")
            else:
                self.send_response(404); self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.uploads.append(self.rfile.read(n))
        self._send(b'{"status":"ok"}')


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), FakeEsp3d)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f"127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_job_header_is_parsed():
    j = parse_job("fluegel.nc", PROGRAM)
    assert (j.block, j.x, j.y, j.root, j.time) == ("124x36x410", "20", "31", "T2", "2.8min")
    assert j.title.startswith("foamcut wing") and j.travel.startswith("X0..134")
    assert parse_job("x.nc", "G21\nG1 X1\n").block == ""


def test_list_read_start_and_stream(server):
    e = Esp3d(server)
    jobs = e.jobs()
    assert [j.name for j in jobs] == ["fluegel.nc"] and jobs[0].block == "124x36x410"
    assert "Processing" in e.start("fluegel.nc")
    assert FakeEsp3d.commands[-1] == "[ESP700]/fluegel.nc"
    st = e.stream()
    assert st["status"] == "processing" and st["processed"] == "40"
    e.stream("pause")
    assert FakeEsp3d.commands[-1].startswith("[ESP701]action=PAUSE")


def test_upload_is_multipart_with_esp3d_field_names(server, tmp_path):
    p = tmp_path / "teil.nc"; p.write_text(PROGRAM)
    Esp3d(server).upload(p)
    body = FakeEsp3d.uploads[-1]
    assert b'name="path"' in body and b'name="teil.ncS"' in body and b'name="myfiles"; filename="teil.nc"' in body
    assert PROGRAM.encode() in body


def test_unreachable_host_is_an_esp_error():
    with pytest.raises(EspError):
        Esp3d("127.0.0.1:1", timeout=0.5).list_files()
