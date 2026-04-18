"""Owner entry point. Walks transcripts/*.json that don't yet have a sibling
findings/*.json and asks Claude Sonnet (via `claude -p`) to produce findings.

This is the step that costs money (paid Claude Code / API access).
Contributors should NOT run this — their job is just transcription.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, time
from pathlib import Path

import config, store

DEBUG_DIR = config.BASE / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

OUT_SCHEMA = {
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

def call_claude(prompt: str, transcript: dict) -> dict:
    meta = transcript
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
        f"{meta['full_text']}\n"
    )
    cmd = [
        "claude", "-p",
        "--model", config.CLAUDE_MODEL,
        "--output-format", "json",
        "--json-schema", json.dumps(OUT_SCHEMA),
        "--tools", "",
        "--disable-slash-commands",
        "--exclude-dynamic-system-prompt-sections",
        "--no-session-persistence",
        "--permission-mode", "bypassPermissions",
    ]
    print(f"[claude] analysing СИК {meta['sik']} ({len(user_msg)} chars)…", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, input=user_msg, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed: {r.stderr.strip()[:600]}")
    raw = DEBUG_DIR / f"claude_{meta['sik']}_tour{meta['tour']}.json"
    raw.write_text(r.stdout, encoding="utf-8")
    env = json.loads(r.stdout)
    print(f"[claude] done in {time.time()-t0:.1f}s", flush=True)
    if isinstance(env.get("structured_output"), dict):
        return env["structured_output"]
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
    raise RuntimeError(f"couldn't parse claude output (see {raw.name})")

def git(*args, check=True):
    r = subprocess.run(["git", *args], text=True, capture_output=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:400]}")
    return r

def analyze_one(t: dict, prompt: str, push: bool) -> bool:
    sik, tour = t["sik"], t["tour"]
    if store.has_findings(sik, tour):
        return False
    try:
        out = call_claude(prompt, t)
    except Exception as e:
        print(f"[analyze] FAILED {sik}: {e}", file=sys.stderr)
        return False
    payload = {
        "schema": "bg-izbori-findings/1",
        "sik": sik, "slug": t["slug"], "tour": tour,
        "video_url": t["video_url"],
        "region_name": t.get("region_name"),
        "address": t.get("address"),
        "town": t.get("town"), "town_type": t.get("town_type"),
        "analyzed_by": "owner",
        "analyzed_at": store.utcnow(),
        "model": config.CLAUDE_MODEL,
        **out,
    }
    p = store.save_findings(payload)
    print(f"[store] {p.relative_to(config.BASE)}  overall={out.get('overall')} "
          f"findings={len(out.get('findings',[]))}")
    if push:
        git("pull","--rebase","--autostash", check=False)
        git("add", str(p))
        git("commit","-m", f"findings: СИК {sik} ({out.get('overall')}, {len(out.get('findings',[]))} signals)",
            check=False)
        git("push", check=False)
    return True

def pull_latest():
    """Fetch + fast-forward main from origin so we see the latest
    volunteer-contributed transcripts."""
    r = subprocess.run(["git","pull","--rebase","--autostash","origin","main"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[git] pull warning: {r.stderr.strip()[:400]}", file=sys.stderr)

def run_once(prompt: str, max_n: int, only_sik: str | None, push: bool) -> int:
    done = 0
    for t in store.iter_transcripts():
        if only_sik and t["sik"] != only_sik: continue
        if store.has_findings(t["sik"], t["tour"]): continue
        if analyze_one(t, prompt, push=push):
            done += 1
            if max_n and done >= max_n: break
    return done

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0, help="stop after N analyses")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--sik", help="only this SIK")
    ap.add_argument("--watch", action="store_true",
                    help="keep running: pull → analyze all new → sleep 60s → repeat")
    ap.add_argument("--interval", type=int, default=60,
                    help="seconds between watch iterations (default 60)")
    args = ap.parse_args()
    prompt = config.PROMPT_PATH.read_text()
    if not args.watch:
        pull_latest()
        n = run_once(prompt, args.max, args.sik, push=not args.no_push)
        print(f"[analyze] processed {n}")
        return
    # watch loop
    print(f"[watch] pulling every {args.interval}s. Ctrl-C to stop.")
    while True:
        try:
            pull_latest()
            n = run_once(prompt, args.max, args.sik, push=not args.no_push)
            if n == 0:
                print(f"[watch] no new transcripts; sleeping {args.interval}s", flush=True)
            else:
                print(f"[watch] analysed {n} new transcripts", flush=True)
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[watch] stopping"); return

if __name__ == "__main__":
    main()
