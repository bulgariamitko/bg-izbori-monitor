"""One pipeline step: take the next pending video, download -> transcribe ->
Sonnet analyse -> store findings -> delete the mp4.

Can be called as:
    python process_video.py              # process one
    python process_video.py --video-id 7 # process a specific row
    python process_video.py --video-id 7 --reanalyze  # skip dl+whisper, just re-run claude
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

import db
import config

DEBUG_DIR = config.BASE / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

# ---- model load is lazy so --help doesn't block --------------------------
_whisper = None
def whisper():
    global _whisper
    if _whisper is None:
        print("[whisper] loading model", config.WHISPER_MODEL, "…", flush=True)
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )
    return _whisper

# ---- picking -------------------------------------------------------------

def pick_next_video() -> dict | None:
    """Pending videos, villages first (priority asc), randomised inside a tier.
    Prefer device recordings (single file) over live (chunks)."""
    row = db.fetchone("""
        SELECT v.*, s.priority, s.address, s.town, s.town_type, s.region_name
        FROM videos v JOIN sections s USING(sik)
        WHERE v.status='pending' AND v.video_type='device'
        ORDER BY s.priority ASC, RANDOM()
        LIMIT 1
    """)
    if row: return row
    # fallback: if no device videos, fall back to live recordings
    return db.fetchone("""
        SELECT v.*, s.priority, s.address, s.town, s.town_type, s.region_name
        FROM videos v JOIN sections s USING(sik)
        WHERE v.status='pending'
        ORDER BY s.priority ASC, RANDOM()
        LIMIT 1
    """)

def set_status(video_id: int, status: str, error: str | None = None, **extra):
    cols = ["status=?"]; params = [status]
    if error is not None: cols.append("error=?"); params.append(error)
    for k,v in extra.items(): cols.append(f"{k}=?"); params.append(v)
    params.append(video_id)
    with db.connect() as c:
        c.execute(f"UPDATE videos SET {', '.join(cols)} WHERE id=?", params)

# ---- download ------------------------------------------------------------

def download(video: dict) -> Path:
    out = config.VIDEOS_DIR / f"{video['sik']}_tour{video['tour']}_{video['video_type']}.mp4"
    if out.exists(): out.unlink()
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", config.COOKIES_FROM_BROWSER,
        "--referer", "https://evideo.bg/",
        "--no-part", "--no-progress", "--quiet",
        "-o", str(out),
        video["video_url"],
    ]
    print(f"[download] {video['sik']} -> {out.name}", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"yt-dlp failed: {r.stderr.strip()[:400]}")
    print(f"[download] {out.stat().st_size/1e6:.1f} MB in {time.time()-t0:.1f}s", flush=True)
    return out

def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe","-hide_banner","-v","error",
         "-show_entries","format=duration","-of","default=nw=1:nk=1", str(path)],
        capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except ValueError: return 0.0

# ---- transcribe ----------------------------------------------------------

def transcribe(path: Path) -> dict:
    print(f"[whisper] transcribing {path.name}", flush=True)
    t0 = time.time()
    segments, info = whisper().transcribe(
        str(path), language="bg",
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        beam_size=1,     # speed over accuracy on long recordings
    )
    segs = [{"start": round(s.start,2), "end": round(s.end,2), "text": s.text.strip()}
            for s in segments]
    full = "\n".join(f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['text']}"
                     for s in segs)
    print(f"[whisper] {len(segs)} segments in {time.time()-t0:.1f}s", flush=True)
    return {"segments": segs, "full_text": full, "duration_sec": info.duration}

# ---- analyse -------------------------------------------------------------

def analyse(transcript_text: str, meta: dict) -> dict:
    """Pipe the transcript + prompt into `claude -p` (headless). Returns parsed JSON."""
    prompt = config.PROMPT_PATH.read_text()
    user_msg = (
        f"{prompt}\n\n"
        f"## Section metadata\n"
        f"- SIK: {meta['sik']}\n"
        f"- Municipality: {meta.get('region_name','?')}\n"
        f"- Address: {meta.get('address','?')}\n"
        f"- Town type: {meta.get('town_type','?')}\n"
        f"- Video URL: {meta['video_url']}\n"
        f"- Tour: {meta['tour']}\n\n"
        f"## Transcript (Bulgarian, lines prefixed with [MM:SS])\n\n"
        f"{transcript_text}\n"
    )
    # Constrain output via --json-schema so Sonnet can't accidentally emit
    # prose / code fences / broken JSON. The schema matches prompt.md.
    out_schema = {
      "type": "object",
      "required": ["overall","summary_bg","summary_en","findings"],
      "properties": {
        "overall":   {"type":"string","enum":["clean","minor_concerns","serious_concerns"]},
        "summary_bg":{"type":"string"},
        "summary_en":{"type":"string"},
        "findings":{"type":"array","items":{
            "type":"object",
            "required":["severity","category","summary","detail","quote","timestamp_sec"],
            "properties":{
              "severity":{"type":"string","enum":["info","low","medium","high","critical"]},
              "category":{"type":"string"},
              "summary":{"type":"string"},
              "detail":{"type":"string"},
              "quote":{"type":"string"},
              "timestamp_sec":{"type":"number"}
            }}}
      }}
    # --bare would strip the system prompt further but requires ANTHROPIC_API_KEY.
    # With OAuth we stay with the default system prompt but disable tools +
    # dynamic sections so the ~7k system prompt stays cached across runs.
    cmd = [
        "claude", "-p",
        "--model", config.CLAUDE_MODEL,
        "--output-format", "json",
        "--json-schema", json.dumps(out_schema),
        "--tools", "",                         # no tool use — pure LLM call
        "--disable-slash-commands",
        "--exclude-dynamic-system-prompt-sections",
        "--no-session-persistence",
        "--permission-mode", "bypassPermissions",
    ]
    print(f"[claude] analysing ({len(user_msg)} chars)…", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, input=user_msg, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed: {r.stderr.strip()[:600]}")
    # stash raw output for debugging every run
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    raw_path = DEBUG_DIR / f"claude_{meta['sik']}_{ts}.json"
    raw_path.write_text(r.stdout, encoding="utf-8")

    env = json.loads(r.stdout)                 # claude's envelope
    print(f"[claude] done in {time.time()-t0:.1f}s", flush=True)

    # With --json-schema, Sonnet's schema-conformant output lands here:
    if isinstance(env.get("structured_output"), dict):
        return env["structured_output"]

    # Fallback: parse `result` text as JSON
    text = (env.get("result") or env.get("text") or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try: return json.loads(text)
    except json.JSONDecodeError: pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try: return json.loads(m.group(0))
        except json.JSONDecodeError: pass
    # Fallback 2: return a single-finding "parse_error" record so we don't lose work
    return {
        "overall": "minor_concerns",
        "summary_bg": "Грешка в парсването на отговора от модела.",
        "summary_en": "Model returned non-JSON output; see debug dir.",
        "findings": [{
            "severity": "info", "category": "other",
            "summary": "Claude output failed JSON parse; raw saved",
            "detail": f"Raw saved to {raw_path.name}. First 300 chars: {text[:300]}",
            "quote": "", "timestamp_sec": 0,
        }],
    }

# ---- main ----------------------------------------------------------------

def reanalyze(video_id: int) -> bool:
    """Re-run only the Claude step using the transcript already in SQLite."""
    db.init()
    row = db.fetchone("""
        SELECT v.*, s.priority, s.address, s.town, s.town_type, s.region_name,
               t.full_text, t.duration_sec AS tdur
        FROM videos v JOIN sections s USING(sik)
        LEFT JOIN transcripts t ON t.video_id=v.id
        WHERE v.id=?""", video_id)
    if not row or not row.get("full_text"):
        print(f"[reanalyze] no transcript for video_id={video_id}"); return False
    print(f"\n=== reanalyze {row['sik']}  {row['region_name']} ===")
    try:
        a = analyse(row["full_text"], row)
        with db.connect() as c:
            c.execute("DELETE FROM findings WHERE video_id=?", (video_id,))
            for f in a.get("findings", []):
                c.execute("""INSERT INTO findings
                  (video_id,severity,category,summary,detail,quote,timestamp_sec)
                  VALUES(?,?,?,?,?,?,?)""",
                  (video_id,
                   f.get("severity","info"), f.get("category","other"),
                   f.get("summary",""), f.get("detail",""),
                   f.get("quote",""),
                   float(f.get("timestamp_sec") or 0)))
            c.execute("""UPDATE videos SET status='analyzed', error=NULL,
                         analyzed_at=? WHERE id=?""",
                      (datetime.utcnow().isoformat(), video_id))
        sev = [f.get("severity") for f in a.get("findings",[])]
        print(f"=== done. overall={a.get('overall')}  findings={len(sev)}  {sev}")
        return True
    except Exception as e:
        print(f"[reanalyze] FAILED: {e}", file=sys.stderr)
        return False

def process(video_id: int | None = None) -> bool:
    db.init()
    row = (db.fetchone("""
            SELECT v.*, s.priority, s.address, s.town, s.town_type, s.region_name
            FROM videos v JOIN sections s USING(sik) WHERE v.id=?""", video_id)
           if video_id else pick_next_video())
    if not row:
        print("[pipeline] no pending videos."); return False

    print(f"\n=== {row['sik']}  {row['region_name']}  ({row['town_type']}) ===")
    vid_id = row["id"]
    mp4 = None
    try:
        set_status(vid_id, "downloading")
        mp4 = download(row)
        dur = probe_duration(mp4)
        set_status(vid_id, "downloaded",
                   bytes=mp4.stat().st_size, duration_sec=dur,
                   downloaded_at="CURRENT_TIMESTAMP" and __import__("datetime").datetime.utcnow().isoformat())

        set_status(vid_id, "transcribing")
        t = transcribe(mp4)
        with db.connect() as c:
            c.execute("""INSERT OR REPLACE INTO transcripts
              (video_id,full_text,segments_json,duration_sec,model)
              VALUES(?,?,?,?,?)""",
              (vid_id, t["full_text"], json.dumps(t["segments"], ensure_ascii=False),
               t["duration_sec"], config.WHISPER_MODEL))
        (config.TRANSCRIPTS / f"{row['sik']}_tour{row['tour']}.txt"
            ).write_text(t["full_text"], encoding="utf-8")
        set_status(vid_id, "transcribed",
                   transcribed_at=__import__("datetime").datetime.utcnow().isoformat())

        set_status(vid_id, "analyzing")
        a = analyse(t["full_text"], row)
        with db.connect() as c:
            for f in a.get("findings", []):
                c.execute("""INSERT INTO findings
                  (video_id,severity,category,summary,detail,quote,timestamp_sec)
                  VALUES(?,?,?,?,?,?,?)""",
                  (vid_id,
                   f.get("severity","info"), f.get("category","other"),
                   f.get("summary",""), f.get("detail",""),
                   f.get("quote",""),
                   float(f.get("timestamp_sec") or 0)))
            c.execute("""UPDATE videos SET status='analyzed',
                         analyzed_at=? WHERE id=?""",
                      (__import__("datetime").datetime.utcnow().isoformat(), vid_id))

        # Delete the mp4
        mp4.unlink(missing_ok=True)
        with db.connect() as c:
            c.execute("UPDATE videos SET deleted_at=? WHERE id=?",
                      (__import__("datetime").datetime.utcnow().isoformat(), vid_id))

        sev = [f.get("severity") for f in a.get("findings",[])]
        print(f"=== done. overall={a.get('overall')}  findings={len(sev)}  {sev}")
        return True

    except Exception as e:
        print(f"[pipeline] FAILED: {e}", file=sys.stderr)
        set_status(vid_id, "failed", error=str(e)[:500])
        # Keep the mp4 on disk so we can retry the analysis without re-downloading.
        return False

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", type=int)
    ap.add_argument("--reanalyze", action="store_true",
                    help="Skip dl+whisper; re-run Claude using the stored transcript")
    args = ap.parse_args()
    if args.reanalyze:
        if not args.video_id:
            print("--reanalyze requires --video-id"); sys.exit(2)
        reanalyze(args.video_id)
    else:
        process(args.video_id)
