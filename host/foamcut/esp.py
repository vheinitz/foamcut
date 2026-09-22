"""Talk to an ESP32 running ESP3D in front of the board: list, upload and
start programs that live in the ESP's flash, watch the stream.

ESP3D 3.x HTTP API (esp3d.io, webhandlers + [ESP7xx] commands):
  GET  /files?path=/                 -> JSON {"files":[{"name","size","time"}, ...], ...}
  POST /files  multipart: path, <name>S (size), myfiles (the file)
  GET  /<name>                       -> the file itself (flash root is the web root)
  GET  /command?cmd=[ESP700]/<name>  -> start processing the file
  GET  /command?cmd=[ESP701]action=PAUSE|RESUME|ABORT, or no action: state as JSON
Everything here was written against the documentation, not a live device;
docs/esp32.md lists what to check on the first contact.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

JOB_PREFIX = "; foamcut-job "


class EspError(RuntimeError):
    pass


@dataclass
class Job:
    """What the header of a program says about its block and placement."""
    name: str
    title: str = ""
    block: str = ""             # LxHxB
    x: str = ""                 # block back face
    y: str = ""                 # table top
    root: str = ""              # T1 / T2
    time: str = ""
    travel: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def parse_job(name: str, text: str) -> Job:
    """The two header lines foamcut writes (any generator)."""
    job = Job(name)
    for line in text.splitlines()[:12]:
        if line.startswith(JOB_PREFIX):
            for tok in line[len(JOB_PREFIX):].split():
                k, _, v = tok.partition("=")
                if k in ("block", "x", "y", "root", "time", "travel"):
                    setattr(job, k, v)
                else:
                    job.extra[k] = v
        elif line.startswith("; foamcut") and not job.title:
            job.title = line[2:].strip()
    return job


class Esp3d:
    def __init__(self, host: str, timeout: float = 10.0, opener=None):
        self.base = host if host.startswith("http") else f"http://{host}"
        self.base = self.base.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    # ------------------------------------------------------------ http ----
    def _get(self, path: str) -> bytes:
        try:
            with self._open(self.base + path, timeout=self.timeout) as r:
                return r.read()
        except OSError as e:
            raise EspError(f"{self.base}{path}: {e}") from e

    def command(self, cmd: str) -> str:
        return self._get("/command?cmd=" + urllib.parse.quote(cmd, safe="[]=/")).decode(errors="replace")

    # ----------------------------------------------------------- files ----
    def list_files(self) -> list[dict]:
        raw = self._get("/files?path=/")
        try:
            data = json.loads(raw)
        except ValueError:
            raise EspError("Dateiliste ist kein JSON: " + raw[:80].decode(errors="replace")) from None
        files = data.get("files", data.get("data", {}).get("files", []) if isinstance(data.get("data"), dict) else [])
        return [f for f in files if isinstance(f, dict) and "name" in f]

    def read(self, name: str) -> str:
        return self._get("/" + urllib.parse.quote(name.lstrip("/"))).decode(errors="replace")

    def jobs(self) -> list[Job]:
        out = []
        for f in self.list_files():
            if f["name"].lower().endswith((".nc", ".gcode", ".gco")):
                out.append(parse_job(f["name"], self.read(f["name"])))
        return out

    def upload(self, path: Path) -> str:
        data = path.read_bytes()
        boundary = "----foamcut" + uuid.uuid4().hex
        parts = [("path", "/"), (f"{path.name}S", str(len(data)))]
        body = b""
        for k, v in parts:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"myfiles\"; filename=\"{path.name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base + "/files", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with self._open(req, timeout=self.timeout) as r:
                return r.read().decode(errors="replace")
        except OSError as e:
            raise EspError(f"Upload {path.name}: {e}") from e

    # ---------------------------------------------------------- stream ----
    def start(self, name: str) -> str:
        return self.command(f"[ESP700]/{name.lstrip('/')}")

    def stream(self, action: str | None = None) -> dict:
        txt = self.command("[ESP701]" + (f"action={action.upper()} " if action else "") + "json=yes")
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return {"raw": txt.strip()}
        try:
            d = json.loads(m.group(0))
        except ValueError:
            return {"raw": txt.strip()}
        return d.get("data", d) if isinstance(d, dict) else {"raw": txt.strip()}
