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
CLAIMS_DIR      = config.BASE / "claims"

SIK_RE = re.compile(r"^\d{9}$")

# Claim TTL — after this a claim is considered abandoned and others may pick it.
# 12h covers long-running owner runs: CPU large-v3/int8 whisper on a 3-4h clip
# can take 4-5h alone (sec 234616006 took 4h 46m), and the sweeper will otherwise
# delete the "expired" claim mid-transcription and break the final push.
CLAIM_TTL_HOURS = 12

for d in (TRANSCRIPTS_DIR, FINDINGS_DIR, CLAIMS_DIR):
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
    d = {"transcript": TRANSCRIPTS_DIR,
         "findings":   FINDINGS_DIR,
         "claim":      CLAIMS_DIR}[kind]
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

# ---------- claims ------------------------------------------------------

def load_claim(sik: str, tour: int) -> dict | None:
    p = _path("claim", sik, tour)
    return json.loads(p.read_text()) if p.exists() else None

def write_claim(sik: str, tour: int, contributor: str) -> Path:
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "schema": "bg-izbori-claim/1",
        "sik": sik, "tour": tour,
        "contributor": contributor or "anon",
        "claimed_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=CLAIM_TTL_HOURS)).isoformat(),
    }
    p = _path("claim", sik, tour)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return p

def claim_is_active(claim: dict, me: str) -> bool:
    """True if this claim should block me from picking the same section."""
    if not claim: return False
    if (claim.get("contributor") or "") == (me or ""):
        return False  # my own claim — I can continue
    from datetime import datetime, timezone
    try:
        exp = datetime.fromisoformat(claim["expires_at"].replace("Z","+00:00"))
    except Exception:
        return False
    return exp > datetime.now(timezone.utc)

def delete_claim(sik: str, tour: int):
    p = _path("claim", sik, tour)
    if p.exists(): p.unlink()

# ---------- utilities ----------------------------------------------------

def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
