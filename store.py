"""File-backed store. Everything lives in the repo as JSON files so volunteers
can commit+push their transcripts without merge conflicts."""
from __future__ import annotations
import json, re
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable

import config

SECTIONS_FILE = config.BASE / "sections.json"
TRANSCRIPTS_DIR = config.BASE / "transcripts"
FINDINGS_DIR    = config.BASE / "findings"

SIK_RE = re.compile(r"^\d{9}$")

for d in (TRANSCRIPTS_DIR, FINDINGS_DIR):
    d.mkdir(exist_ok=True)

# ---------- sections -----------------------------------------------------

def load_sections() -> list[dict]:
    if not SECTIONS_FILE.exists(): return []
    return json.loads(SECTIONS_FILE.read_text())

def save_sections(sections: list[dict]):
    sections.sort(key=lambda s: (s.get("priority", 9), s["sik"]))
    SECTIONS_FILE.write_text(json.dumps(sections, ensure_ascii=False, indent=2))

# ---------- per-section files -------------------------------------------

def _path(kind: str, sik: str, tour: int) -> Path:
    d = TRANSCRIPTS_DIR if kind == "transcript" else FINDINGS_DIR
    return d / f"{sik}_tour{tour}.json"

def has_transcript(sik: str, tour: int) -> bool:
    return _path("transcript", sik, tour).exists()

def has_findings(sik: str, tour: int) -> bool:
    return _path("findings", sik, tour).exists()

def load_transcript(sik: str, tour: int) -> dict | None:
    p = _path("transcript", sik, tour)
    return json.loads(p.read_text()) if p.exists() else None

def load_findings(sik: str, tour: int) -> dict | None:
    p = _path("findings", sik, tour)
    return json.loads(p.read_text()) if p.exists() else None

def save_transcript(payload: dict) -> Path:
    assert SIK_RE.match(payload["sik"]), "bad sik"
    p = _path("transcript", payload["sik"], payload["tour"])
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return p

def save_findings(payload: dict) -> Path:
    p = _path("findings", payload["sik"], payload["tour"])
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return p

def iter_transcripts() -> Iterable[dict]:
    for p in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        try: yield json.loads(p.read_text())
        except json.JSONDecodeError: continue

def iter_findings() -> Iterable[dict]:
    for p in sorted(FINDINGS_DIR.glob("*.json")):
        try: yield json.loads(p.read_text())
        except json.JSONDecodeError: continue

# ---------- utilities ----------------------------------------------------

def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
