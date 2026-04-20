"""Owner-side one-stop loop.

Does everything in order:
  1. pick the next section (high-risk villages first)
  2. download video(s), whisper-transcribe
  3. save transcript, git-push it
  4. run claude sonnet analysis
  5. save findings, git-push them
  6. rebuild dashboard.html
  7. print a compact Bulgarian summary
  8. repeat

Run:
  python owner.py                 # forever until you Ctrl-C
  python owner.py --max 10        # stop after 10 sections
  python owner.py --once          # one section, then exit
  python owner.py --sik 093500013 # a specific SIK (useful for retries)

Must be executed inside the upstream repo (origin =
bulgariamitko/bg-izbori-monitor), so pushes land directly on main
without the fork+PR dance volunteers use.
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

import config, store
import contribute        # has download(), transcribe(), whisper(), pick_section, _publish_claim, git_publish
import analyze           # has call_claude(), analyze_one(), pull_latest()
import dashboard

GH_HANDLE = "bulgariamitko"

# ---- nice-to-have reporting ---------------------------------------------
SEV_BG   = {"critical":"КРИТ","high":"ВИС","medium":"СРЕД","low":"НИСКО","info":"ИНФО"}
OVERALL_BG = {"clean":"чисто","minor_concerns":"леки съмнения","serious_concerns":"сериозни съмнения"}

def _fmt(sec: float | int | None) -> str:
    s = int(sec or 0)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def _print_findings(findings_payload: dict, section: dict):
    print("="*70)
    print(f"СИК {section['sik']} · {section.get('region_name')} · "
          f"{section.get('town','')} ({section.get('town_type','?')})")
    print(f"оценка: {OVERALL_BG.get(findings_payload.get('overall'), findings_payload.get('overall'))}")
    print(f"\nКратко: {findings_payload.get('summary_bg','')}\n")
    for i, f in enumerate(findings_payload.get("findings", []), 1):
        sev = SEV_BG.get(f.get("severity"), f.get("severity"))
        ts  = _fmt(f.get("timestamp_sec"))
        print(f"  {i}. [{sev}] {ts}  {f.get('summary','')}")
        if f.get("quote"): print(f"     «{f['quote']}»")
    print("="*70)

# ---- one iteration ------------------------------------------------------

def _git(*args, check=False):
    r = subprocess.run(["git",*args], text=True, capture_output=True)
    if check and r.returncode: raise RuntimeError(f"git {args[0]}: {r.stderr.strip()[:300]}")
    return r

def process_one(slug: str, sik_filter: str | None = None) -> bool:
    """Pick → transcribe → claude → push → dashboard. Returns False if
    there was nothing to do."""
    if sik_filter:
        sections = [s for s in store.load_sections()
                    if s.get("slug") == slug and s["sik"] == sik_filter]
        if not sections:
            print(f"[owner] no section matches {sik_filter}"); return False
        section = sections[0]
        # reuse contribute's lazy fetch to get a proper group
        fresh = contribute._fetch_section_videos(section)
        PREF = ("device","live_hls","live")
        chosen = None
        for kind in PREF:
            urls = sorted([v["url"] for v in fresh if v["type"]==kind],
                          key=contribute._chunk_sort_key)
            if urls: chosen = {"tour": 1, "type": kind, "urls": urls}; break
        if not chosen:
            print(f"[owner] no video URLs for {sik_filter}"); return False
        pick = (section, chosen)
    else:
        pick = contribute.pick_section(slug, GH_HANDLE)
        if not pick: print("[owner] nothing to do."); return False

    section, group = pick
    sik, tour = section["sik"], group["tour"]

    # skip if already fully done
    if store.has_transcript(sik, tour) and store.has_findings(sik, tour) and not sik_filter:
        return True

    # ---------- 1. CLAIM -------------------------------------------------
    claim_path = store.write_claim(sik, tour, GH_HANDLE)
    if not contribute._publish_claim(claim_path, sik, tour):
        print(f"[owner] claim push failed for {sik}")
        store.delete_claim(sik, tour); return True   # skip, continue loop
    _git("pull","--rebase","--autostash")

    # ---------- 2. TRANSCRIBE -------------------------------------------
    # --sik forces re-transcribe so a bad recording (e.g. first-minute-only
    # truncation from a broken mp4 concat) can be redone cleanly.
    if not store.has_transcript(sik, tour) or sik_filter:
        audio  = config.VIDEOS_DIR / f"{sik}_tour{tour}.wav"
        tmpdir = config.VIDEOS_DIR / f"{sik}_tour{tour}.chunks"
        if audio.exists(): audio.unlink()
        try:
            contribute.download(group["urls"], audio, tmpdir)
            t = contribute.transcribe(audio)
            payload = {
                "schema": "bg-izbori-transcript/1",
                "sik": sik, "slug": slug, "tour": tour,
                "video_url": group["urls"][0],
                "video_type": group["type"],
                "chunk_count": len(group["urls"]),
                "video_chunks": contribute.build_video_chunks(group["urls"]),
                "duration_sec": t["duration_sec"],
                "region_name": section.get("region_name"),
                "address": section.get("address"),
                "town": section.get("town"),
                "town_type": section.get("town_type"),
                "risk_level": contribute.load_risk_tiers().get(sik),
                "whisper": {
                    "model": config.WHISPER_MODEL,
                    "language": "bg",
                    "compute_type": config.WHISPER_COMPUTE,
                },
                "contributed_by": GH_HANDLE,
                "transcribed_at": store.utcnow(),
                "segments": t["segments"],
                "full_text": t["full_text"],
            }
            tp = store.save_transcript(payload)
            # release claim on the same push
            claim_file = store._path("claim", sik, tour)
            paths = [tp] + ([claim_file] if claim_file.exists() else [])
            if claim_file.exists(): claim_file.unlink()
            contribute.git_publish(paths, sik, tour, push=True)
        finally:
            if audio.exists(): audio.unlink()
            if tmpdir.exists():
                for p in tmpdir.iterdir():
                    try: p.unlink()
                    except Exception: pass
                try: tmpdir.rmdir()
                except Exception: pass

    # ---------- 3. CLAUDE ANALYSIS --------------------------------------
    if not store.has_findings(sik, tour) or sik_filter:
        t = store.load_transcript(sik, tour)
        if not t:
            print(f"[owner] transcript vanished for {sik}"); return True
        prompt = config.PROMPT_PATH.read_text()
        analyze.analyze_one(t, prompt, push=True)

    # ---------- 4. LOCAL DASHBOARD --------------------------------------
    try: dashboard.build()
    except Exception as e: print(f"[owner] dashboard rebuild failed: {e}", file=sys.stderr)

    # ---------- 5. REPORT -----------------------------------------------
    f = store.load_findings(sik, tour)
    if f: _print_findings(f, section)
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug",  default=config.SLUG)
    ap.add_argument("--max",   type=int, default=0)
    ap.add_argument("--once",  action="store_true")
    ap.add_argument("--sik",   help="only this SIK (useful for retries / testing)")
    args = ap.parse_args()

    print(f"[owner] slug={args.slug}  handle={GH_HANDLE}")
    done = 0
    while True:
        try:
            ok = process_one(args.slug, args.sik)
        except KeyboardInterrupt:
            print("\n[owner] stopping"); return
        except Exception as e:
            print(f"[owner] iteration failed: {e}", file=sys.stderr)
            ok = False
        if not ok and not args.sik: break   # no more work
        done += 1
        if args.once or args.sik: break
        if args.max and done >= args.max: break
    print(f"[owner] processed {done}")

if __name__ == "__main__":
    main()
