"""Fetch the tibroish.bg risk classification for every Bulgarian section and
write it to risk_tiers.json so contribute.py can prioritise high-risk first.

tibroish.bg (Ти Броиш, Anti-Corruption Fund) publishes a hierarchical JSON
index of every polling section with a `riskLevel` = "high" | "mid" | null
based on historical statistical anomalies (atypical turnout, atypically
concentrated results etc.).

Run:
    python risk_tiers.py                    # writes risk_tiers.json
    python risk_tiers.py --min-level high   # only high-risk
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import requests

import config

BASE = "https://api.tibroish.bg/results"
HEADERS = {"Accept":"application/json","Accept-Language":"bg-BG"}

def get(segment: str) -> dict:
    url = f"{BASE}/{segment}.json" if segment else f"{BASE}/index.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def walk(node, out: dict):
    """Recursively find all 'section' nodes and record their risk level."""
    if isinstance(node, dict):
        if node.get("type") == "section":
            sik = node.get("segment") or node.get("id")
            if sik and len(str(sik)) == 9:
                out[str(sik)] = node.get("riskLevel")  # "high"|"mid"|null
        for v in node.values(): walk(v, out)
    elif isinstance(node, list):
        for v in node: walk(v, out)

def scrape() -> dict:
    """Walk root → regions → municipalities → towns → addresses → sections.
    The municipality-level response already embeds all sections, so we only
    need to fetch each municipality segment once."""
    out = {}
    print("[risk] fetching root …", flush=True)
    root = get("")
    regions = root.get("nodes", [])
    for ri, r in enumerate(regions, 1):
        reg_seg = r.get("segment") or r.get("id")
        if not reg_seg: continue
        print(f"[risk] region {reg_seg} ({r.get('name')}) – {len(regions)-ri} regions left …", flush=True)
        try:
            reg = get(reg_seg)
        except Exception as e:
            print(f"  region {reg_seg} FAIL: {e}", file=sys.stderr); continue
        munis = reg.get("nodes", [])
        for m in munis:
            muni_seg = m.get("segment")
            if not muni_seg: continue
            try:
                muni = get(muni_seg)
            except Exception as e:
                print(f"  muni {muni_seg} FAIL: {e}", file=sys.stderr); continue
            before = len(out)
            walk(muni, out)
            time.sleep(0.08)  # be polite
        high = sum(1 for v in out.values() if v=="high")
        mid  = sum(1 for v in out.values() if v=="mid")
        print(f"  region {reg_seg}: cumulative highRisk={high}  midRisk={mid}  sections={len(out)}")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(config.BASE / "risk_tiers.json"))
    args = ap.parse_args()
    data = scrape()
    Path(args.out).write_text(json.dumps(
        {"source":"https://api.tibroish.bg","fetched_at":__import__("datetime").datetime.utcnow().isoformat(),
         "tiers": data}, ensure_ascii=False, indent=2))
    high = sum(1 for v in data.values() if v=="high")
    mid  = sum(1 for v in data.values() if v=="mid")
    print(f"[risk] wrote {args.out}  ({len(data)} sections, highRisk={high}, midRisk={mid})")

if __name__ == "__main__":
    main()
