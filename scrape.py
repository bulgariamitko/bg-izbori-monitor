"""Build / refresh sections.json from evideo.bg.

Fills in everything a contributor needs to pick and download a video:
  sik, slug, tour, region_name, address, town, town_type, priority,
  video_urls: [{tour, type, url}, ...]
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path
import urllib.parse as up

from bs4 import BeautifulSoup
from curl_cffi import requests

import config, store

VILLAGE_RE = re.compile(r"^\s*С\.\s*", re.I)   # accept "С. Х" and "С.Х"
CITY_RE    = re.compile(r"^\s*ГР\.\s*", re.I)  # accept "ГР. Х" and "ГР.Х"
BIG_CITIES = {"СОФИЯ", "ПЛОВДИВ", "ВАРНА", "БУРГАС", "РУСЕ", "СТАРА ЗАГОРА"}
SERVERS_RE = re.compile(r'var\s+servers\s*=\s*(\{[^}]+\})')

def _session(slug: str):
    s = requests.Session(impersonate=config.IMPERSONATE)
    s.headers.update(config.HEADERS)
    s.get(f"https://evideo.bg/{slug}/index.html")
    return s

def _classify_town(addr: str) -> tuple[str, str, int]:
    addr = addr.strip()
    if VILLAGE_RE.match(addr):
        town = addr[VILLAGE_RE.match(addr).end():].split(" ")[0].strip(",").strip()
        return town, "village", 0
    if CITY_RE.match(addr):
        town = addr[CITY_RE.match(addr).end():].split(" ")[0].strip(",").strip()
        t = "city" if town.upper() in BIG_CITIES else "town"
        return town, t, (2 if t=="city" else 1)
    return "", "unknown", 9

def discover_oik_pages(sess, slug):
    r = sess.get(f"https://evideo.bg/{slug}/index.html"); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out, seen = [], set()
    for a in soup.select("ul.oik__list li a.oik"):
        href = a.get("href","").lstrip("./")
        if not href or href in seen: continue
        seen.add(href)
        span = a.find("span")
        out.append({
            "href": href,
            "rik": (span.get_text(strip=True) if span else "").replace("ОИК ","").replace("РИК ",""),
            "name": a.get_text(" ", strip=True).replace(span.get_text(strip=True) if span else "", "").strip(),
        })
    return out

def parse_oik_page(slug, page_url, html):
    soup = BeautifulSoup(html, "html.parser")

    # -------- servers map (only used by le* archive format) --------
    servers = {}
    for s in soup.find_all("script"):
        m = SERVERS_RE.search(s.text or "")
        if m:
            raw = m.group(1)
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict): servers = parsed
            except json.JSONDecodeError: pass
            break

    # -------- sections with address --------
    sections = {}
    for sec in soup.select("[data-sik]"):
        sik = sec.get("data-sik","")
        if not store.SIK_RE.match(sik): continue
        text = " ".join(sec.stripped_strings)
        text = re.sub(rf"^{sik}\s*", "", text)
        text = re.sub(r"\s*(ЗАПИСИ|излъчване)\s*$", "", text, flags=re.I).strip()
        town, ttype, prio = _classify_town(text)
        sections.setdefault(sik, {
            "sik": sik, "slug": slug,
            "rik": sik[:2], "muni_code": sik[:4],
            "region_name": page_url.split("/")[-1].replace(".html",""),
            "oik_page": page_url,
            "address": text, "town": town,
            "town_type": ttype, "priority": prio,
            "videos": [],
        })

    # -------- videos --------
    for btn in soup.select("button[data-vid]"):
        try:  vid = json.loads(btn.get("data-vid", "null"))
        except json.JSONDecodeError: continue
        sik_el = btn.find_parent(attrs={"data-sik": True})
        if not sik_el: continue
        sik = sik_el["data-sik"]
        if sik not in sections: continue
        tour = int(btn.get("data-tour", "1"))

        # ----- format 1: le* archive. data-vid is a dict {"d":[...],"r":[...]}
        #                 where each entry is "<serverKey>#/<path>" and the
        #                 server URL lives in the `servers` var.
        if isinstance(vid, dict):
            for kind, urls in (("device", vid.get("d",[])), ("live", vid.get("r",[]))):
                for u in urls:
                    if "#" not in u: continue
                    key, path = u.split("#", 1)
                    base = servers.get(key)
                    if not base: continue
                    full = up.urljoin(base if base.endswith("/") else base+"/",
                                      f"{sik}/{path.lstrip('/')}")
                    sections[sik]["videos"].append({
                        "tour": tour, "type": kind, "url": full,
                    })

        # ----- format 2: pe* live HLS. data-vid is a plain list of full URLs.
        elif isinstance(vid, list):
            for u in vid:
                if not isinstance(u, str): continue
                kind = "live_hls" if u.endswith(".m3u8") else "device"
                sections[sik]["videos"].append({
                    "tour": tour, "type": kind, "url": u,
                })

    return list(sections.values())

def run(slug: str, limit: int = 0):
    sess = _session(slug)
    pages = discover_oik_pages(sess, slug)
    if limit: pages = pages[:limit]
    print(f"[scrape] {slug}: {len(pages)} OIK/RIK pages")
    all_sections = []
    for i, p in enumerate(pages, 1):
        url = f"https://evideo.bg/{slug}/{p['href']}"
        try:
            r = sess.get(url); r.raise_for_status()
            secs = parse_oik_page(slug, url, r.text)
            # use nice municipality name from index listing
            for s in secs: s["region_name"] = p["name"]
            all_sections.extend(secs)
            print(f"  [{i:>3}/{len(pages)}] {p['rik']:>4} {p['name']:<25} {len(secs)} sections")
        except Exception as e:
            print(f"  [{i:>3}/{len(pages)}] {p['name']}  FAIL: {e}", file=sys.stderr)
        time.sleep(0.3)
    store.save_sections(all_sections)
    print(f"[scrape] wrote {store.SECTIONS_FILE}  ({len(all_sections)} sections)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=config.SLUG)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    run(args.slug, args.limit)
