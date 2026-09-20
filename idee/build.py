#!/usr/bin/env python3
"""Baut aus idee/raw/*.txt die HTML-Dateien idee/chat_<datum>_<slug>.html
plus idee/index.html.

Rohformat (aus dem ChatGPT-Backend exportiert):

    ### id: <conversation id>
    ### title: <Titel>
    ### create: <unix time>
    ### update: <unix time>
    === user <unix time> ===
    <Markdown>
    === assistant <unix time> ===
    <Markdown>

Fuehrende Leerzeichen sind als "·" kodiert (der Browser-Export hat
Einrueckungen verschluckt).
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
PROJECT_URL = "https://chatgpt.com/g/g-p-69c3ebacd09081919d16054124f6bb4c-flugzeugbaukasten"

CSS = """
body{font-family:sans-serif;max-width:900px;margin:2em auto;padding:0 1em;line-height:1.45;color:#222}
section{margin:1.2em 0;padding:.6em 1.2em;border-radius:8px}
section.user{background:#e8f0fe}
section.assistant{background:#f6f6f6}
section h4{margin:0 0 .4em;font-size:.85em;color:#666;font-weight:normal}
section h1{font-size:1.3em}section h2{font-size:1.15em}section h3{font-size:1.05em}
table{border-collapse:collapse;margin:.6em 0}
td,th{border:1px solid #ccc;padding:.2em .6em;text-align:left;vertical-align:top}
pre{background:#eee;padding:.6em;overflow-x:auto;border-radius:4px}
code{background:#eee;padding:0 .2em;border-radius:3px}
pre code{background:none;padding:0}
blockquote{border-left:3px solid #bbb;margin:.6em 0;padding:.1em .8em;color:#444}
hr{border:0;border-top:1px solid #ddd;margin:1em 0}
.math{font-family:monospace;color:#333}
nav a{margin-right:1em}
"""

# KaTeX-Autorender, falls online; sonst bleibt die LaTeX-Quelle lesbar stehen.
KATEX = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
 onload="renderMathInElement(document.body,{delimiters:[{left:'\\\\[',right:'\\\\]',display:true},{left:'\\\\(',right:'\\\\)',display:false}],throwOnError:false});"></script>
"""

HEAD_RE = re.compile(r"^### (\w+): (.*)$")
MSG_RE = re.compile(r"^=== (user|assistant) ([\d.]+) ===$")


def parse_raw(path: Path) -> dict:
    meta: dict[str, str] = {}
    msgs: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = MSG_RE.match(line)
        if m:
            cur = {"role": m.group(1), "t": float(m.group(2)), "lines": []}
            msgs.append(cur)
            continue
        if cur is None:
            h = HEAD_RE.match(line)
            if h:
                meta[h.group(1)] = h.group(2).strip()
            continue
        cur["lines"].append(line)
    for m in msgs:
        m["text"] = "\n".join(m["lines"]).strip("\n")
        del m["lines"]
    meta["msgs"] = msgs
    return meta


def clean(text: str) -> str:
    """ChatGPT-Interna entfernen, kodierte Einrueckung zurueckwandeln."""
    text = re.sub(r"^([·→]+)", lambda m: m.group(1).replace("·", " ").replace("→", "\t"), text, flags=re.M)
    text = re.sub(r"^image_group\{.*\}\s*$", "", text, flags=re.M)
    text = re.sub(r"^product\[.*\]\s*$", "", text, flags=re.M)
    text = re.sub(r"\s*cite[\w:]*turn\d+\w+\d*", "", text)
    text = re.sub(r"entity\[\"[^\"]*\",\"([^\"]*)\"(?:,\"[^\"]*\")?\]", r"\1", text)
    text = re.sub(r"genui\{\"math_block_widget[^\"]*\":\s*\{\"content\":\s*\"((?:[^\"\\]|\\.)*)\"\}\}",
                  lambda m: "\\[\n" + m.group(1).encode().decode("unicode_escape") + "\n\\]", text)
    text = text.replace("citeturn", "")
    return text


def render_md(text: str) -> str:
    return markdown.markdown(
        clean(text),
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )


def slug(name: str) -> str:
    return name.stem


def fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def fmt_dt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


def build_chat(path: Path) -> tuple[Path, dict]:
    conv = parse_raw(path)
    title = conv["title"]
    created = float(conv["create"])
    updated = float(conv["update"])
    url = f"{PROJECT_URL}/c/{conv['id']}"
    out = HERE / f"chat_{fmt_date(created)}_{slug(path)}.html"
    parts = [
        "<!DOCTYPE html>", '<html lang="de"><head><meta charset="utf-8">',
        f"<title>{html.escape(title)}</title>", f"<style>{CSS}</style>", KATEX, "</head><body>",
        '<nav><a href="index.html">← Übersicht</a></nav>',
        f"<h1>{html.escape(title)}</h1>",
        f"<p><small>ChatGPT-Projekt „Flugzeugbaukasten“ · {fmt_dt(created)} bis {fmt_dt(updated)} · "
        f"{len(conv['msgs'])} Beiträge · <a href=\"{url}\">Quelle</a> · exportiert 2026-09-17</small></p>",
    ]
    for m in conv["msgs"]:
        who = "Valentin" if m["role"] == "user" else "ChatGPT"
        parts.append(f'<section class="{m["role"]}"><h4>{who} · {fmt_dt(m["t"])}</h4>')
        parts.append(render_md(m["text"]))
        parts.append("</section>")
    parts.append("</body></html>")
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out, {"title": title, "created": created, "updated": updated, "n": len(conv["msgs"]), "url": url}


def build_index(entries: list[tuple[Path, dict]]) -> None:
    entries.sort(key=lambda e: e[1]["created"])
    rows = "\n".join(
        f'<tr><td>{fmt_date(i["created"])}</td><td><a href="{p.name}">{html.escape(i["title"])}</a></td>'
        f'<td>{i["n"]}</td><td><a href="{i["url"]}">ChatGPT</a></td></tr>'
        for p, i in entries
    )
    doc = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Ideen – Flugzeugbaukasten</title><style>{CSS}</style></head>
<body>
<h1>Flugzeugbaukasten – ChatGPT-Diskussionen</h1>
<p>Export des ChatGPT-Projekts <a href="{PROJECT_URL}/project">Flugzeugbaukasten</a> (Stand 2026-09-17).
Die Inhalte sind Hinweise und Ideen aus der Planungsphase, keine festen Vorgaben.
Destillat für die Doku: <a href="distilled.md">distilled.md</a>, Zukunftsideen: <a href="zukunft.md">zukunft.md</a>.</p>
<table><thead><tr><th>Beginn</th><th>Chat</th><th>Beiträge</th><th>Original</th></tr></thead><tbody>
{rows}
</tbody></table>
<p><small>Rohdaten in <code>raw/</code>, Generator <code>build.py</code>.</small></p>
</body></html>
"""
    (HERE / "index.html").write_text(doc, encoding="utf-8")


def main() -> int:
    entries = [build_chat(p) for p in sorted(RAW.glob("*.txt"))]
    build_index(entries)
    for p, i in sorted(entries, key=lambda e: e[1]["created"]):
        print(f"{p.name}: {i['n']} Beiträge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
