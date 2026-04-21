"""Volunteer entry point. Picks one section nobody has transcribed yet,
runs faster-whisper on the recording, and pushes the JSON transcript back.

Run:
    python contribute.py              # one section, auto-push
    python contribute.py --no-push    # don't git-push (just commit locally)
    python contribute.py --loop       # keep going forever
    python contribute.py --gh-handle myname  # tag your contributions
"""
from __future__ import annotations
import argparse, hashlib, json, os, random, subprocess, sys, time
from pathlib import Path

import config, store

# Lazy import — only when we need to fetch fresh video URLs
def _fetch_section_videos(section: dict) -> list[dict]:
    """Re-fetch the OIK page for this section and parse out current video
    URLs. Needed because sections.json stores only chunk_count to stay
    small; the real URLs are fetched on demand."""
    import scrape as _sc
    from curl_cffi import requests
    s = requests.Session(impersonate=config.IMPERSONATE)
    s.headers.update(config.HEADERS)
    s.get(f"https://evideo.bg/{section['slug']}/index.html")
    r = s.get(section["oik_page"]); r.raise_for_status()
    rows = _sc.parse_oik_page(section["slug"], section["oik_page"], r.text)
    for row in rows:
        if row["sik"] == section["sik"]:
            return row.get("videos", [])
    return []

RISK_FILE = config.BASE / "risk_tiers.json"
RISK_RANK = {"high": 0, "mid": 1}   # smaller = picked first

def load_risk_tiers() -> dict:
    if not RISK_FILE.exists(): return {}
    try: return json.loads(RISK_FILE.read_text()).get("tiers", {})
    except Exception: return {}

def run_cmd(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, text=True, capture_output=True, **kw)

# ----- load whisper lazily ------------------------------------------------

_whisper = None
def whisper():
    global _whisper
    if _whisper is None:
        print(f"[whisper] loading {config.WHISPER_MODEL} …", flush=True)
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )
    return _whisper

# ----- section picking ---------------------------------------------------

def _user_hash(sik: str, gh_handle: str) -> int:
    """Stable 64-bit hash so each volunteer walks the section list in a
    different order — halves the collision probability before claim files
    even come into play."""
    h = hashlib.sha256(f"{gh_handle}:{sik}".encode()).digest()
    return int.from_bytes(h[:8], "big")

def _chunk_sort_key(url: str) -> str:
    """Sort by the YYYYMMDDHHMMSS timestamp embedded in the filename."""
    name = url.rsplit("/",1)[-1]
    return name[:14]   # first 14 chars are the timestamp prefix

def build_video_chunks(urls: list[str]) -> list[dict]:
    """Per-chunk start offset (in seconds from session start), derived from
    the YYYYMMDDHHMMSS filename prefix. Good enough for deep-linking findings
    back to the originating video — skips the cost of probing each wav file
    and works even for findings generated before we saved chunk metadata."""
    from datetime import datetime
    out: list[dict] = []
    t0 = None
    for u in urls:
        name = u.rsplit("/",1)[-1][:14]
        try:
            t = datetime.strptime(name, "%Y%m%d%H%M%S")
        except ValueError:
            out.append({"url": u, "start_sec": 0}); continue
        if t0 is None: t0 = t
        out.append({"url": u, "start_sec": int((t - t0).total_seconds())})
    return out

def pick_section(slug: str, gh_handle: str) -> tuple[dict, dict] | None:
    """Return (section, chosen_video_group).

    chosen_video_group = {"tour": int, "type": "device"|"live_hls"|"live",
                          "urls": [url, …]}  — one URL for device/HLS,
                          many chunks sorted chronologically for 'live'.

    Priority: high-risk → mid-risk → villages → towns → cities.
    Deterministic per-volunteer ordering within a tier.
    """
    sections = [s for s in store.load_sections() if s.get("slug") == slug]
    risk = load_risk_tiers()
    def key(s):
        r = risk.get(s["sik"])
        tier = RISK_RANK[r] if r in RISK_RANK else 2 + s.get("priority", 9)
        return (tier, _user_hash(s["sik"], gh_handle or "anon"))
    sections.sort(key=key)

    me = gh_handle or ""
    PREF = ("device", "live_hls", "live")
    for s in sections:
        vids = s.get("videos", [])
        # Compact stored form has {tour, type, chunk_count}; full form has
        # {tour, type, url}. Pick the preferred (tour, type) either way.
        chosen = None
        for kind in PREF:
            for v in vids:
                if v["type"] == kind: chosen = v; break
            if chosen: break
        if not chosen: continue
        tour = chosen["tour"]
        if store.has_transcript(s["sik"], tour): continue
        claim = store.load_claim(s["sik"], tour)
        if store.claim_is_active(claim, me): continue
        # Fetch actual URLs lazily if needed
        if "url" in chosen:  # legacy full form
            urls = [v["url"] for v in vids if v["tour"] == tour and v["type"] == chosen["type"]]
            urls.sort(key=_chunk_sort_key)
        else:
            fresh = _fetch_section_videos(s)
            urls = [v["url"] for v in fresh if v["tour"] == tour and v["type"] == chosen["type"]]
            urls.sort(key=_chunk_sort_key)
            if not urls:
                print(f"[pick] no URLs found after refetch for {s['sik']} — skipping",
                      file=sys.stderr)
                continue
        return s, {"tour": tour, "type": chosen["type"], "urls": urls}
    return None

# ----- pipeline steps ----------------------------------------------------

def _yt_dlp(url: str, out: Path, hls: bool):
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", config.COOKIES_FROM_BROWSER,
        "--referer", "https://evideo.bg/",
        "--no-part", "--no-progress", "--quiet", "--no-warnings",
    ]
    if hls:
        cmd += ["--live-from-start","--hls-use-mpegts","--merge-output-format","mp4"]
    cmd += ["-o", str(out), url]
    r = run_cmd(cmd)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"yt-dlp failed for {url}: {r.stderr.strip()[:300]}")

_cookies_header_cache: str | None = None
def _evideo_cookies_for_ffmpeg() -> str:
    # Exported once per process: faster than the yt-dlp round-trip on every
    # chunk, and good enough since Cloudflare cookies live for hours.
    global _cookies_header_cache
    if _cookies_header_cache is not None:
        return _cookies_header_cache
    jar_path = config.BASE / ".evideo-cookies.txt"
    cmd = ["yt-dlp",
           "--cookies-from-browser", config.COOKIES_FROM_BROWSER,
           "--cookies", str(jar_path),
           "--skip-download", "--no-warnings", "--quiet",
           "https://evideo.bg/"]
    run_cmd(cmd)
    if not jar_path.exists():
        _cookies_header_cache = ""
        return ""
    import http.cookiejar
    cj = http.cookiejar.MozillaCookieJar(str(jar_path))
    try: cj.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        _cookies_header_cache = ""; return ""
    parts = []
    for c in cj:
        if "evideo.bg" not in (c.domain or ""): continue
        parts.append(f"{c.name}={c.value}; path={c.path or '/'}; domain={c.domain}")
    _cookies_header_cache = "\r\n".join(parts)
    return _cookies_header_cache

# Flat 20 dB gain + look-ahead limiter keeps whisper in its sweet spot even
# when the camera is across the room (polling footage often runs at -25 dB
# mean; VAD + no_speech heuristics drop most of it). dynaudnorm tried before
# only lifted 2 dB because peak limiter clamped to ~0 dBFS. The alimiter
# here prevents actual clipping without compressing quiet passages away.
AUDIO_FILTER = "volume=20dB,alimiter=limit=0.98:attack=5:release=50"

def _stream_audio_only(url: str, wav: Path):
    """Stream audio directly from the URL. For faststart mp4 on servers that
    honor Range, ffmpeg reads the moov atom then byte-range GETs only audio
    sample ranges — saves roughly 75% bandwidth versus downloading the full
    mp4. Falls through to the caller's fallback if ffmpeg can't auth or
    range-read the source."""
    cookies = _evideo_cookies_for_ffmpeg()
    cmd = ["ffmpeg","-hide_banner","-v","error",
           "-err_detect","ignore_err",
           "-fflags","+genpts+discardcorrupt",
           "-user_agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
           "-headers", "Referer: https://evideo.bg/\r\n",
           "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
           "-seekable","1","-multiple_requests","1"]
    if cookies:
        cmd += ["-cookies", cookies]
    cmd += ["-i", url,
            "-vn","-ac","1","-ar","16000","-af", AUDIO_FILTER,
            "-c:a","pcm_s16le",
            "-y", str(wav)]
    r = run_cmd(cmd)
    if r.returncode != 0 or not wav.exists() or wav.stat().st_size < 1024:
        if wav.exists(): wav.unlink()
        raise RuntimeError(f"ffmpeg audio stream failed: {r.stderr.strip()[:200]}")

def _extract_audio(src: Path, wav: Path):
    # `-c copy` concat silently truncates when codec params differ between
    # inputs, so go through per-chunk PCM extraction instead. Error-tolerant
    # flags push through PTS discontinuities that would otherwise stop decode.
    cmd = ["ffmpeg","-hide_banner","-v","error",
           "-err_detect","ignore_err",
           "-fflags","+genpts+discardcorrupt",
           "-i", str(src),
           "-vn","-ac","1","-ar","16000","-af", AUDIO_FILTER,
           "-c:a","pcm_s16le",
           "-y", str(wav)]
    r = run_cmd(cmd)
    if r.returncode != 0 or not wav.exists():
        raise RuntimeError(f"audio extract failed: {r.stderr.strip()[:300]}")

def _probe_duration(src: Path) -> float | None:
    """Return container duration in seconds via ffprobe, or None on failure."""
    r = run_cmd(["ffprobe","-v","error","-show_entries","format=duration",
                 "-of","default=nw=1:nk=1", str(src)])
    if r.returncode != 0: return None
    try: return float(r.stdout.strip())
    except ValueError: return None

def _silent_wav(wav: Path, duration_sec: float):
    """Generate a 16 kHz mono PCM WAV of silence — used to preserve timeline
    when a chunk has no decodable audio stream so downstream timestamps stay
    aligned with the original video."""
    dur = max(0.1, float(duration_sec))
    cmd = ["ffmpeg","-hide_banner","-v","error",
           "-f","lavfi","-i", f"anullsrc=channel_layout=mono:sample_rate=16000",
           "-t", f"{dur:.3f}",
           "-c:a","pcm_s16le","-y", str(wav)]
    r = run_cmd(cmd)
    if r.returncode != 0 or not wav.exists():
        raise RuntimeError(f"silent wav generation failed: {r.stderr.strip()[:200]}")

def _fetch_chunk_audio(url: str, wav_out: Path, tmpdir: Path, idx: int,
                       duration_hint: float | None = None):
    """Produce a wav from one source URL. Tries audio-only streaming first;
    falls back to full download + local extract. If the chunk has no audio
    stream at all, emit silence of `duration_hint` seconds so the combined
    timeline stays aligned with the original video."""
    try:
        _stream_audio_only(url, wav_out)
        return
    except Exception as e:
        print(f"[audio] chunk {idx}: streaming failed ({e}) — falling back to full download",
              file=sys.stderr, flush=True)
    tmp_src = tmpdir / f"chunk_{idx:05d}.mp4"
    _yt_dlp(url, tmp_src, hls=url.endswith(".m3u8"))
    try:
        try:
            _extract_audio(tmp_src, wav_out)
            return
        except Exception as e:
            msg = str(e)
            # "Output file does not contain any stream" → no audio track in the
            # source. Use the video's own duration (or the caller's hint) and
            # emit silence so subsequent chunk timestamps are not shifted.
            if "does not contain any stream" not in msg:
                raise
            dur = _probe_duration(tmp_src) or duration_hint
            if not dur:
                raise
            print(f"[audio] chunk {idx}: no audio stream — inserting {dur:.1f}s silence to preserve timeline",
                  file=sys.stderr, flush=True)
            _silent_wav(wav_out, dur)
    finally:
        tmp_src.unlink(missing_ok=True)

def download(urls: list[str], out: Path, tmpdir: Path):
    """Download one video or many chunks and produce a single WAV at `out`.

    Output is always 16kHz mono PCM WAV so whisper reads the whole recording
    even when live-archive chunks have mismatched codec parameters between
    recording sessions (a straight mp4 `-c copy` concat would truncate at the
    first discontinuity, leaving whisper with only the first minute).
    """
    tmpdir.mkdir(parents=True, exist_ok=True)
    if out.exists(): out.unlink()
    if len(urls) == 1:
        print(f"[download] {urls[0].rsplit('/',1)[-1]} (audio-only) …", flush=True)
        t0 = time.time()
        try:
            _stream_audio_only(urls[0], out)
            print(f"[download] audio {out.stat().st_size/1e6:.1f} MB in {time.time()-t0:.1f}s",
                  flush=True)
            return
        except Exception as e:
            print(f"[download] streaming failed ({e}) — full download fallback",
                  file=sys.stderr, flush=True)
        tmp_src = tmpdir / "single.mp4"
        _yt_dlp(urls[0], tmp_src, hls=urls[0].endswith(".m3u8"))
        print(f"[download] {tmp_src.stat().st_size/1e6:.1f} MB in {time.time()-t0:.1f}s", flush=True)
        _extract_audio(tmp_src, out)
        tmp_src.unlink(missing_ok=True)
        return
    step = 1 if len(urls) <= 20 else 10
    print(f"[download] {len(urls)} chunks (audio-only) "
          f"(progress every {step} chunk{'s' if step!=1 else ''}) …", flush=True)
    t0 = time.time()
    # Derive each chunk's expected duration from the filename-encoded start
    # time of the next chunk. Keeps the timeline aligned when a chunk has no
    # audio track (silence is inserted for its hinted duration).
    chunk_meta = build_video_chunks(urls)
    duration_hints: list[float | None] = []
    for i, m in enumerate(chunk_meta):
        nxt = chunk_meta[i+1]["start_sec"] if i+1 < len(chunk_meta) else None
        duration_hints.append(
            max(1.0, float(nxt - m["start_sec"])) if nxt is not None else None)
    wav_parts: list[Path] = []
    total_mb = 0.0
    for i, u in enumerate(urls, 1):
        wav_p = tmpdir / f"chunk_{i:05d}.wav"
        t_chunk = time.time()
        hint = duration_hints[i-1]
        try:
            _fetch_chunk_audio(u, wav_p, tmpdir, i, duration_hint=hint)
            total_mb += wav_p.stat().st_size / 1e6
            wav_parts.append(wav_p)
        except Exception as e:
            # Preserve the timeline: if we know how long the chunk should be,
            # emit silence instead of dropping it. Dropping would shift every
            # subsequent finding timestamp earlier than the real video.
            if hint:
                try:
                    _silent_wav(wav_p, hint)
                    total_mb += wav_p.stat().st_size / 1e6
                    wav_parts.append(wav_p)
                    print(f"[audio] chunk {i}/{len(urls)} failed ({e}) — "
                          f"inserted {hint:.1f}s silence",
                          file=sys.stderr, flush=True)
                    continue
                except Exception as e2:
                    print(f"[audio] chunk {i}/{len(urls)} silence fallback also failed ({e2})",
                          file=sys.stderr, flush=True)
            print(f"[audio] chunk {i}/{len(urls)} failed entirely ({e}) — skipping",
                  file=sys.stderr, flush=True)
        if i % step == 0 or i == len(urls):
            dt = time.time() - t0
            eta = dt/i*(len(urls)-i) if i else 0
            print(f"  [{i}/{len(urls)}] {total_mb:.1f} MB audio so far, "
                  f"elapsed {dt:.0f}s, eta {eta:.0f}s "
                  f"(last chunk {time.time()-t_chunk:.1f}s)",
                  flush=True)
    if not wav_parts:
        raise RuntimeError("no chunks produced any audio — aborting")
    # All wav chunks share identical PCM codec params, so concat -c copy is safe.
    list_file = tmpdir / "audio_concat.txt"
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in wav_parts))
    cmd = ["ffmpeg","-hide_banner","-v","error","-f","concat","-safe","0",
           "-i", str(list_file), "-c","copy","-y", str(out)]
    r = run_cmd(cmd)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"ffmpeg wav concat failed: {r.stderr.strip()[:400]}")
    for p in wav_parts: p.unlink(missing_ok=True)
    list_file.unlink(missing_ok=True)
    print(f"[download] audio wav -> {out.stat().st_size/1e6:.1f} MB "
          f"({len(wav_parts)}/{len(urls)} chunks), total {time.time()-t0:.1f}s",
          flush=True)

def transcribe(path: Path) -> dict:
    print(f"[whisper] transcribing {path.name}", flush=True)
    t0 = time.time()
    segments, info = whisper().transcribe(
        str(path), language="bg",
        vad_filter=True,
        # threshold=0.2 keeps far-field quiet speech; min_silence 800ms keeps
        # VAD from chopping mid-sentence during natural pauses.
        vad_parameters={"threshold": 0.2, "min_silence_duration_ms": 800},
        beam_size=1,
        # Low-signal polling footage (far mic, whispered counting) trips the
        # compression-ratio / logprob fallbacks; without these clamps the
        # decoder hallucinates Latin/foreign tokens during quiet stretches.
        condition_on_previous_text=False,
        no_speech_threshold=0.3,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
    )
    total = float(getattr(info, "duration", 0) or 0)
    print(f"[whisper] audio duration: {total/60:.1f} min (model={config.WHISPER_MODEL} "
          f"compute={config.WHISPER_COMPUTE}). Progress every 60s of decoded audio.",
          flush=True)
    segs = []
    next_tick = 60.0
    last_print = time.time()
    for s in segments:
        segs.append({"start": round(s.start,2), "end": round(s.end,2),
                     "text": s.text.strip()})
        # Print on decoded-audio milestones OR at least every 20s wall time,
        # so the user sees heartbeat even during long silent stretches.
        now = time.time()
        if s.end >= next_tick or now - last_print > 20:
            elapsed = now - t0
            frac = (s.end / total) if total else 0
            eta = (elapsed / frac - elapsed) if frac > 0.01 else 0
            speed = (s.end / elapsed) if elapsed > 0 else 0
            print(f"[whisper] {s.end/60:5.1f}/{total/60:5.1f} min decoded "
                  f"({frac*100:4.1f}%)  elapsed {elapsed/60:4.1f}m  "
                  f"eta {eta/60:4.1f}m  speed {speed:.2f}x  segs={len(segs)}",
                  flush=True)
            while next_tick <= s.end: next_tick += 60.0
            last_print = now
    full = "\n".join(
        f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['text']}" for s in segs)
    print(f"[whisper] {len(segs)} segments in {time.time()-t0:.1f}s", flush=True)
    return {"segments": segs, "full_text": full, "duration_sec": info.duration}

def git(*args, check=True):
    r = run_cmd(["git", *args])
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:400]}")
    return r

UPSTREAM = "upstream"       # added during install as bulgariamitko/bg-izbori-monitor

def _upstream_exists() -> bool:
    return run_cmd(["git","remote","get-url",UPSTREAM]).returncode == 0

def _origin_is_upstream() -> bool:
    """If the user runs directly on the origin repo (owner), not a fork."""
    origin = run_cmd(["git","remote","get-url","origin"]).stdout.strip()
    return "bulgariamitko/bg-izbori-monitor" in origin

def git_publish(paths: list[Path], sik: str, tour: int, push: bool):
    """Per-transcript branch → push to fork → open PR → auto-merger handles it.

    Owner (origin == upstream repo) pushes directly to main and skips the PR.
    """
    if not push: return
    direct_to_main = _origin_is_upstream() or not _upstream_exists()

    # make sure main is up-to-date
    if _upstream_exists():
        git("fetch", UPSTREAM, "main", check=False)
        git("checkout", "main", check=False)
        git("reset", "--hard", f"{UPSTREAM}/main", check=False)
    else:
        git("pull", "--rebase", "--autostash", check=False)

    # Filter paths that still exist OR are tracked by git. The sweeper workflow
    # may delete our expired claim file between claim-time and transcript-time
    # on a long CPU whisper run, so the path no longer exists on disk AND was
    # reset out of the index by the fetch+reset above — `git add` would fail.
    # Losing the claim file here is harmless: we're about to commit the work.
    add_paths: list[str] = []
    for p in paths:
        if p.exists():
            add_paths.append(str(p)); continue
        tracked = run_cmd(["git","ls-files","--error-unmatch", str(p)]).returncode == 0
        if tracked:
            add_paths.append(str(p))
        else:
            print(f"[git] skipping add for missing+untracked path {p.name}", flush=True)

    if direct_to_main:
        for p in add_paths: git("add", p)
        git("commit","-m", f"transcript: СИК {sik} (tour {tour})", check=False)
        r = git("push", check=False)
        if r.returncode == 0:
            print(f"[git] pushed transcript directly to main")
        else:
            print(f"[git] push failed:\n{r.stderr}", file=sys.stderr)
        return

    # Fork + PR flow
    branch = f"transcript/{sik}-tour{tour}"
    git("checkout", "-B", branch)
    for p in add_paths: git("add", p)
    msg = f"transcript: СИК {sik} (tour {tour})"
    git("commit","-m", msg, check=False)
    r = git("push", "--set-upstream", "origin", branch, "--force", check=False)
    if r.returncode != 0:
        print(f"[git] push failed:\n{r.stderr}", file=sys.stderr); return

    # open PR via gh (also auto-enables auto-merge)
    pr = run_cmd([
        "gh","pr","create",
        "--repo","bulgariamitko/bg-izbori-monitor",
        "--base","main","--head", f"{_gh_user()}:{branch}",
        "--title", msg,
        "--body", f"Auto-generated transcript for СИК {sik}, tour {tour}.\n\n"
                  f"Produced by `contribute.py` using faster-whisper "
                  f"`{config.WHISPER_MODEL}`. Will auto-merge after the "
                  f"`validate-transcripts` workflow passes.",
    ])
    if pr.returncode != 0 and "already exists" not in (pr.stderr or ""):
        print(f"[gh] pr create: {pr.stderr.strip()[:300]}", file=sys.stderr)
    else:
        print(f"[gh] PR opened / updated for {branch}")

    # back to main, ready for next section
    git("checkout","main", check=False)

def _gh_user() -> str:
    r = run_cmd(["gh","api","user","--jq",".login"])
    return r.stdout.strip() if r.returncode == 0 else ""

def _publish_claim(path: Path, sik: str, tour: int) -> bool:
    """Publish a claim file via a tiny PR that auto-merges in ~20 s. Returns
    False if the push failed (likely because someone else already claimed
    this SIK in the race window)."""
    direct_to_main = _origin_is_upstream() or not _upstream_exists()
    if _upstream_exists():
        git("fetch", UPSTREAM, "main", check=False)
        git("checkout", "main", check=False)
        git("reset","--hard", f"{UPSTREAM}/main", check=False)
    else:
        git("pull","--rebase","--autostash", check=False)
    # If another volunteer's claim already landed for this SIK, their file
    # now exists on main — skip.
    if path.exists() and path.stat().st_size and (config.BASE / "claims" / path.name).exists():
        pass  # either fresh from upstream (then it's their claim) or ours
    # re-write our claim (upstream might have wiped it during reset)
    if not path.exists():
        # upstream had someone else's claim for same SIK → bail out
        return False
    if direct_to_main:
        git("add", str(path))
        git("commit","-m", f"claim: СИК {sik} (tour {tour})", check=False)
        return git("push", check=False).returncode == 0

    branch = f"claim/{sik}-tour{tour}"
    git("checkout", "-B", branch)
    git("add", str(path))
    git("commit","-m", f"claim: СИК {sik} (tour {tour})", check=False)
    r = git("push","--set-upstream","origin",branch,"--force", check=False)
    if r.returncode != 0:
        print(f"[claim] push failed:\n{r.stderr}", file=sys.stderr)
        git("checkout","main", check=False); return False
    pr = run_cmd([
        "gh","pr","create",
        "--repo","bulgariamitko/bg-izbori-monitor",
        "--base","main","--head", f"{_gh_user()}:{branch}",
        "--title", f"claim: СИК {sik} (tour {tour})",
        "--body", f"Volunteer `{_gh_user()}` is claiming SIK {sik} tour {tour} "
                  f"for the next {store.CLAIM_TTL_HOURS} hours to avoid duplicate work.",
    ])
    git("checkout","main", check=False)
    if pr.returncode != 0 and "already exists" not in (pr.stderr or ""):
        print(f"[claim] pr create: {pr.stderr.strip()[:300]}", file=sys.stderr)
        return False
    print(f"[claim] claim PR opened for {sik}")
    return True

# ----- main orchestration ------------------------------------------------

def contribute_one(slug: str, gh_handle: str | None, push: bool) -> bool:
    pick = pick_section(slug, gh_handle or "")
    if not pick:
        print("[contribute] nothing to do — all sections have a transcript!")
        return False
    section, group = pick
    sik, tour = section["sik"], group["tour"]
    risk = load_risk_tiers().get(sik)
    risk_tag = f" [риск:{risk}]" if risk else ""
    n_urls = len(group["urls"])
    chunks_tag = f" · {n_urls} chunks" if n_urls > 1 else ""
    print(f"\n=== СИК {sik}{risk_tag}  {section.get('region_name')}  "
          f"{section.get('town','')} ({section.get('town_type','?')}) — "
          f"tour {tour}{chunks_tag} ===")

    # Place a claim FIRST so concurrent volunteers see we're working on this
    # SIK. Push it to GitHub ASAP via a small PR that auto-merges.
    if push:
        claim_path = store.write_claim(sik, tour, gh_handle or "anon")
        if not _publish_claim(claim_path, sik, tour):
            store.delete_claim(sik, tour)
            print("[contribute] claim push failed, trying next section", file=sys.stderr)
            return True

    audio = config.VIDEOS_DIR / f"{sik}_tour{tour}.wav"
    tmpdir = config.VIDEOS_DIR / f"{sik}_tour{tour}.chunks"
    if audio.exists(): audio.unlink()
    try:
        download(group["urls"], audio, tmpdir)
        t = transcribe(audio)
        payload = {
            "schema": "bg-izbori-transcript/1",
            "sik": sik, "slug": slug, "tour": tour,
            "video_url": group["urls"][0],
            "video_type": group["type"],
            "chunk_count": n_urls,
            "video_chunks": build_video_chunks(group["urls"]),
            "duration_sec": t["duration_sec"],
            "region_name": section.get("region_name"),
            "address": section.get("address"),
            "town": section.get("town"), "town_type": section.get("town_type"),
            "risk_level": load_risk_tiers().get(sik),  # high | mid | null
            "whisper": {
                "model": config.WHISPER_MODEL,
                "language": "bg",
                "compute_type": config.WHISPER_COMPUTE,
            },
            "contributed_by": gh_handle or "",
            "transcribed_at": store.utcnow(),
            "segments": t["segments"],
            "full_text": t["full_text"],
        }
        p = store.save_transcript(payload)
        print(f"[store] wrote {p.relative_to(config.BASE)}")
        # Release the claim as part of the same commit
        claim_file = store._path("claim", sik, tour)
        extra_paths = [p]
        if claim_file.exists():
            claim_file.unlink()  # local delete
            extra_paths.append(claim_file)
        git_publish(extra_paths, sik, tour, push=push)
        return True
    finally:
        if audio.exists(): audio.unlink()
        # clean up chunk tmpdir
        if tmpdir.exists():
            for p in tmpdir.iterdir():
                try: p.unlink()
                except Exception: pass
            try: tmpdir.rmdir()
            except Exception: pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=config.SLUG)
    ap.add_argument("--gh-handle", default=os.environ.get("GH_HANDLE",""))
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--loop", action="store_true", help="keep going until no work left")
    args = ap.parse_args()
    while True:
        ok = contribute_one(args.slug, args.gh_handle, push=not args.no_push)
        if not ok: break
        if not args.loop: break

if __name__ == "__main__":
    main()
