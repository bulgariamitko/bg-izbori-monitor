"""Scrape every section (СИК) from evideo.bg/{SLUG}/ into SQLite.

Cloudflare blocks stock curl/requests, so we use curl_cffi with Chrome
impersonation + a warm Chrome session on the user's machine.

Usage:
    python scrape_sections.py            # discovers all OIK/RIK pages and all sections
    python scrape_sections.py --slug le20260420
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path
from curl_cffi import requests
from bs4 import BeautifulSoup

import db
import config

VILLAGE_RE = re.compile(r"^\s*С\.\s+", re.I)      # "С. ГАБРЕНЕ" — село
CITY_RE    = re.compile(r"^\s*ГР\.\s+", re.I)     # "ГР. ПЕТРИЧ" — град
BIG_CITIES = {"СОФИЯ", "ПЛОВДИВ", "ВАРНА", "БУРГАС", "РУСЕ", "СТАРА ЗАГОРА"}

def _session(slug: str) -> requests.Session:
    s = requests.Session(impersonate=config.IMPERSONATE)
    s.headers.update(config.HEADERS)
    # prime the index once so CF hands out a cookie
    s.get(f"https://evideo.bg/{slug}/index.html")
    return s

def _classify_town(addr: str) -> tuple[str, str]:
    """Return (town, town_type). town_type in village|town|city|unknown."""
    addr = addr.strip()
    m_city = CITY_RE.match(addr)
    m_vil  = VILLAGE_RE.match(addr)
    if m_vil:
        rest = addr[m_vil.end():]
        town = rest.split(" ")[0].strip(",").strip()
        return town, "village"
    if m_city:
        rest = addr[m_city.end():]
        town = rest.split(" ")[0].strip(",").strip()
        t = "city" if town.upper() in BIG_CITIES else "town"
        return town, t
    return "", "unknown"

def _priority(town_type: str) -> int:
    # smaller = processed first; villages first as requested
    return {"village": 0, "town": 1, "city": 2, "unknown": 9}[town_type]

def discover_oik_pages(sess, slug: str) -> list[dict]:
    """Return [{href,name,rik}, ...] from the main index."""
    r = sess.get(f"https://evideo.bg/{slug}/index.html")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    seen = set()
    for a in soup.select("ul.oik__list li a.oik"):
        href = a.get("href", "").lstrip("./")
        if not href or href in seen: continue
        seen.add(href)
        span = a.find("span")
        out.append({
            "href": href,
            "rik":  (span.get_text(strip=True) if span else "").replace("ОИК ","").replace("РИК ",""),
            "name": a.get_text(" ", strip=True).replace(span.get_text(strip=True) if span else "", "").strip(),
        })
    return out

def scrape_oik_page(sess, slug: str, page: dict) -> list[dict]:
    url = f"https://evideo.bg/{slug}/{page['href']}"
    r = sess.get(url); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    rows = []
    for sec in soup.select("[data-sik]"):
        sik = sec.get("data-sik","").strip()
        if not sik or len(sik) != 9: continue
        num_div = sec.select_one(".section__number")
        # address is the rest of the inner text, sans the SIK number and "ЗАПИСИ" button
        text = " ".join(sec.stripped_strings)
        text = re.sub(rf"^{sik}\s*", "", text)
        text = re.sub(r"\s*ЗАПИСИ\s*$", "", text)
        town, ttype = _classify_town(text)
        rows.append({
            "sik":         sik,
            "slug":        slug,
            "rik":         sik[:2],
            "muni_code":   sik[:4],
            "region_name": page["name"],
            "oik_page":    url,
            "address":     text.strip(),
            "town":        town,
            "town_type":   ttype,
            "priority":    _priority(ttype),
        })
    return rows

def upsert_sections(rows: list[dict]) -> int:
    if not rows: return 0
    with db.connect() as c:
        c.executemany("""
            INSERT INTO sections(sik,slug,rik,muni_code,region_name,oik_page,
                                 address,town,town_type,priority)
            VALUES(:sik,:slug,:rik,:muni_code,:region_name,:oik_page,
                   :address,:town,:town_type,:priority)
            ON CONFLICT(sik) DO UPDATE SET
                slug=excluded.slug, region_name=excluded.region_name,
                oik_page=excluded.oik_page, address=excluded.address,
                town=excluded.town, town_type=excluded.town_type,
                priority=excluded.priority
        """, rows)
    return len(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=config.SLUG)
    ap.add_argument("--limit-oik", type=int, default=0,
                    help="Process only first N OIK pages (for testing)")
    args = ap.parse_args()

    db.init()
    sess = _session(args.slug)
    pages = discover_oik_pages(sess, args.slug)
    if args.limit_oik: pages = pages[:args.limit_oik]
    print(f"[scrape] {args.slug}: {len(pages)} OIK/RIK pages")

    total = 0
    for i, p in enumerate(pages, 1):
        try:
            rows = scrape_oik_page(sess, args.slug, p)
            n = upsert_sections(rows)
            total += n
            print(f"  [{i:>3}/{len(pages)}] {p['rik']:>4} {p['name']:<25} {n:>4} sections")
        except Exception as e:
            print(f"  [{i:>3}/{len(pages)}] {p['name']}  FAILED: {e}", file=sys.stderr)
        time.sleep(0.5)

    config.SECTIONS_JSON.write_text(json.dumps(
        db.fetchall("SELECT * FROM sections WHERE slug=? ORDER BY priority, sik", args.slug),
        ensure_ascii=False, indent=2))
    print(f"[scrape] done — {total} sections written.  cache: {config.SECTIONS_JSON}")

if __name__ == "__main__":
    main()
