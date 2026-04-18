"""For each known section, visit its OIK page, find the ЗАПИСИ buttons and
insert video rows into the DB.

The ЗАПИСИ button carries:
    data-tour="1"
    data-vid='{"d":["r0#/..mp4"],"r":["r1#/..mp4",...]}'

and the page has an inline script:
    var servers = {"r0":"https:\/\/archive.evideo.bg\/..\/","r1":"..."}

We rebuild full URLs and prefer the single 'd' (device) file.
"""
from __future__ import annotations
import argparse, json, re, sys, time, urllib.parse as up
from bs4 import BeautifulSoup
from curl_cffi import requests

import db
import config

SERVERS_RE = re.compile(r'var\s+servers\s*=\s*(\{[^}]+\})')

def _session(slug: str):
    s = requests.Session(impersonate=config.IMPERSONATE)
    s.headers.update(config.HEADERS)
    s.get(f"https://evideo.bg/{slug}/index.html")
    return s

def parse_oik_page(html: str) -> tuple[dict[str,str], list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    servers = {}
    for s in soup.find_all("script"):
        m = SERVERS_RE.search(s.text or "")
        if m:
            servers = json.loads(m.group(1))
            break
    entries = []
    for btn in soup.select("button.u-btn-record, button[data-vid]"):
        tour = int(btn.get("data-tour", "1"))
        try:
            vid = json.loads(btn.get("data-vid", "{}"))
        except json.JSONDecodeError:
            continue
        sik_el = btn.find_parent(attrs={"data-sik": True})
        if not sik_el: continue
        sik = sik_el["data-sik"]
        # device (d) = single full-session mp4. live (r) = chunks.
        for kind, urls in (("device", vid.get("d", [])), ("live", vid.get("r", []))):
            for u in urls:
                if "#" not in u: continue
                key, path = u.split("#", 1)
                base = servers.get(key)
                if not base: continue
                # Both device and live recordings live under /{SIK}/{filename}
                # (confirmed on le20260222). The raw path in data-vid omits
                # the SIK segment — we have to splice it in.
                filename = path.lstrip("/")
                full = up.urljoin(base if base.endswith("/") else base+"/",
                                  f"{sik}/{filename}")
                entries.append({
                    "sik": sik, "tour": tour, "video_type": kind,
                    "video_url": full,
                })
    return servers, entries

def run(slug: str, limit: int = 0):
    db.init()
    sess = _session(slug)
    pages = db.fetchall("SELECT DISTINCT oik_page FROM sections WHERE slug=?", slug)
    if limit: pages = pages[:limit]
    total = 0
    for i, row in enumerate(pages, 1):
        url = row["oik_page"]
        try:
            r = sess.get(url); r.raise_for_status()
            servers, entries = parse_oik_page(r.text)
        except Exception as e:
            print(f"  [{i:>3}/{len(pages)}] {url}  FAIL: {e}", file=sys.stderr)
            continue
        with db.connect() as c:
            for e in entries:
                try:
                    c.execute("""
                      INSERT OR IGNORE INTO videos(sik,slug,tour,video_url,video_type,status)
                      VALUES(?,?,?,?,?,'pending')""",
                      (e["sik"], slug, e["tour"], e["video_url"], e["video_type"]))
                    total += c.total_changes and 0  # noop — just using total below
                except Exception as ex:
                    print("   insert err:", ex, file=sys.stderr)
        print(f"  [{i:>3}/{len(pages)}] {url.split('/')[-1]}  {len(entries)} videos")
        time.sleep(0.3)
    n = db.fetchone("SELECT COUNT(*) c FROM videos WHERE slug=?", slug)["c"]
    print(f"[discover] done — {n} video rows in DB for {slug}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=config.SLUG)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    run(args.slug, args.limit)
