"""Generate dashboard.html from sections.json + transcripts/*.json + findings/*.json.

Pure file-system read; no SQLite. Runs locally (owner) and inside GH Actions
(to publish a public page via GitHub Pages).
"""
from __future__ import annotations
import html, json
from datetime import datetime, timezone
from pathlib import Path

import config, store

SEV_ORDER   = ["critical", "high", "medium", "low", "info"]
SEV_COLORS  = {"critical":"#b00020","high":"#d9480f","medium":"#d98e0f","low":"#6b7280","info":"#9ca3af"}
SEV_BG      = {"critical":"критично","high":"високо","medium":"средно","low":"ниско","info":"инфо"}
CAT_BG = {
    "tampering":"манипулация","miscounting":"грешно броене","protocol":"протокол",
    "intimidation":"заплахи","unauthorized":"неуп. лица","procedure":"процедура",
    "dispute":"спор","other":"друго",
}
TTYPE_BG = {"village":"село","town":"град (малък)","city":"голям град","unknown":"—"}
OVERALL_BG = {
    "clean":"чисто", "minor_concerns":"леки съмнения", "serious_concerns":"сериозни съмнения",
}
OVERALL_COLORS = {"clean":"#059669","minor_concerns":"#d98e0f","serious_concerns":"#b00020"}

def _fmt_ts(s) -> str:
    s = int(s or 0)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def h(x) -> str: return html.escape(str(x or ""))

def build():
    sections   = store.load_sections()
    by_sik     = {s["sik"]: s for s in sections}
    transcripts_all = list(store.iter_transcripts())
    findings_all    = list(store.iter_findings())

    def is_current(row):
        return (row.get("slug") == config.SLUG) and not row.get("demo")

    transcripts   = [t for t in transcripts_all if is_current(t)]
    findings_rows = [f for f in findings_all    if is_current(f)]

    finding_keys    = {(f["sik"], f["tour"]) for f in findings_rows}
    transcript_keys = {(t["sik"], t["tour"]) for t in transcripts}

    def flatten(rows):
        out = []
        for f in rows:
            for item in f.get("findings", []):
                out.append({**item,
                    "sik": f["sik"], "tour": f["tour"], "slug": f.get("slug"),
                    "video_url": f["video_url"],
                    "video_chunks": f.get("video_chunks") or [],
                    "region_name": f.get("region_name") or by_sik.get(f["sik"],{}).get("region_name"),
                    "town": f.get("town") or by_sik.get(f["sik"],{}).get("town"),
                    "town_type": f.get("town_type") or by_sik.get(f["sik"],{}).get("town_type"),
                    "address": f.get("address") or by_sik.get(f["sik"],{}).get("address"),
                    "overall": f.get("overall"),
                    "demo": bool(f.get("demo")),
                })
        sev_rank = {s:i for i,s in enumerate(SEV_ORDER)}
        out.sort(key=lambda x: (sev_rank.get(x.get("severity"),9), -float(x.get("timestamp_sec") or 0)))
        return out

    flat      = flatten(findings_rows)

    sev_counts = {s:0 for s in SEV_ORDER}
    for x in flat: sev_counts[x.get("severity","info")] = sev_counts.get(x.get("severity","info"),0)+1

    overall_counts = {"clean":0,"minor_concerns":0,"serious_concerns":0}
    for f in findings_rows: overall_counts[f.get("overall","clean")] = overall_counts.get(f.get("overall","clean"),0)+1

    # risk-tier coverage
    risk_file = config.BASE / "risk_tiers.json"
    risk_tiers = {}
    try:
        risk_tiers = json.loads(risk_file.read_text()).get("tiers", {}) if risk_file.exists() else {}
    except Exception: pass
    high_total  = sum(1 for v in risk_tiers.values() if v == "high")
    mid_total   = sum(1 for v in risk_tiers.values() if v == "mid")
    high_done   = sum(1 for t in transcripts if risk_tiers.get(t["sik"]) == "high")
    mid_done    = sum(1 for t in transcripts if risk_tiers.get(t["sik"]) == "mid")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parts = [f"""<!DOCTYPE html>
<html lang="bg"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>БГ Избори · СИК видеонаблюдение ({h(config.SLUG)})</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;margin:0;background:#f7f7f8;color:#111}}
header{{background:#111;color:#fff;padding:16px 24px}}
header h1{{margin:0;font-size:20px}}
header .sub{{font-size:13px;opacity:.75;margin-top:4px}}
main{{max-width:1200px;margin:0 auto;padding:24px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px}}
.card .n{{font-size:22px;font-weight:600}} .card .l{{font-size:12px;color:#6b7280}}
section{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:24px;overflow:hidden}}
section h2{{margin:0;padding:12px 16px;font-size:15px;background:#fafafa;border-bottom:1px solid #eee}}
.finding{{padding:12px 16px;border-bottom:1px solid #f1f1f1;display:grid;grid-template-columns:110px 1fr;gap:12px}}
.finding:last-child{{border-bottom:none}}
.sev{{font-size:11px;text-transform:uppercase;font-weight:700;color:#fff;padding:2px 8px;border-radius:4px;display:inline-block}}
.meta{{color:#6b7280;font-size:12px;margin-top:4px}}
.quote{{background:#fff7ed;border-left:3px solid #f59e0b;padding:6px 10px;margin-top:6px;font-size:13px;font-style:italic}}
a{{color:#2563eb;text-decoration:none}} a:hover{{text-decoration:underline}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:8px 12px;border-bottom:1px solid #f1f1f1;text-align:left}}
th{{background:#fafafa;font-weight:600;font-size:12px;color:#6b7280}}
.tag{{font-size:11px;padding:2px 6px;border-radius:4px;background:#eef2ff;color:#3730a3;margin-left:6px}}
.village{{background:#dcfce7;color:#14532d}} .town{{background:#e0f2fe;color:#075985}} .city{{background:#fef3c7;color:#78350f}}
.disclaimer{{background:#fff8e1;border:1px solid #f5d97b;padding:12px 16px;border-radius:8px;margin-bottom:24px;font-size:13px}}
.join{{background:#ecfccb;border:1px solid #84cc16;padding:14px 18px;border-radius:8px;margin-bottom:20px;font-size:14px;color:#365314}}
.join pre{{background:#111;color:#f1f5f9;padding:10px 12px;border-radius:6px;font-size:12.5px;overflow-x:auto;margin:0;white-space:pre-wrap;word-break:break-all}}
.join code{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
.join a{{color:#166534;text-decoration:underline}}
.overall-dot{{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:6px;vertical-align:middle}}
.controls{{padding:10px 16px;background:#fafafa;border-bottom:1px solid #eee;font-size:13px;display:flex;gap:18px;flex-wrap:wrap}}
.controls label{{display:inline-flex;align-items:center;gap:6px;color:#374151}}
.controls select{{padding:4px 8px;border:1px solid #d1d5db;border-radius:4px;background:#fff;font-size:13px}}
.risk-high{{background:#fee2e2;color:#991b1b}} .risk-mid{{background:#fef3c7;color:#78350f}} .risk-low{{background:#ecfccb;color:#365314}}
footer{{text-align:center;color:#6b7280;font-size:12px;padding:24px}}
</style></head><body>
<header>
  <h1>БГ Избори · видеонаблюдение на СИК ({h(config.SLUG)})</h1>
  <div class="sub">разпределен граждански преглед · обновено {h(now)}
    · <a href="https://github.com/bulgariamitko/bg-izbori-monitor" style="color:#9cf">код</a></div>
</header>
<main>
<div class="join">
  <h2 style="margin:0 0 6px 0;font-size:17px">Как да помогнете ▸ станете доброволец</h2>
  <p style="margin:0 0 10px 0">
    <strong>След 20:00 часа българско време на 19.04.2026</strong> видеата на СИК-овете
    стават достъпни. Колкото повече компютри работят, толкова повече секции
    ще бъдат транскрибирани и анализирани. Нужни са ви: Mac / Linux / Windows
    компютър, 10 GB свободно място, и един GitHub акаунт (безплатен,
    създава се за 1 минута).
  </p>
  <p style="margin:0 0 10px 0">
    💸 <strong>Напълно безплатно.</strong> Никакви абонаменти, API ключове или
    плащания. Единственото, което се иска от вас, е процесорното време на
    компютъра ви (и малко ток). Целият софтуер —
    <a href="https://github.com/SYSTRAN/faster-whisper" target="_blank">faster-whisper</a>,
    <a href="https://yt-dlp.org/" target="_blank">yt-dlp</a>,
    <a href="https://cli.github.com/" target="_blank">GitHub CLI</a> —
    е отворен код. Скъпата стъпка (Claude Sonnet анализ) се поема от автора,
    а вашият принос е локалната транскрипция.
  </p>
  <p style="margin:0 0 6px 0;font-weight:600">На macOS или Linux — едно копиране в Terminal:</p>
  <pre><code>bash &lt;(curl -sSL https://raw.githubusercontent.com/bulgariamitko/bg-izbori-monitor/main/install.sh)</code></pre>
  <p style="margin:10px 0 6px 0;font-weight:600">На Windows — едно копиране в PowerShell:</p>
  <pre><code>iwr -useb https://raw.githubusercontent.com/bulgariamitko/bg-izbori-monitor/main/install.ps1 | iex</code></pre>
  <p style="margin:10px 0 0 0;font-size:12px;color:#475569">
    Скриптът сам инсталира Python / ffmpeg / yt-dlp / GitHub CLI, влиза в
    GitHub (ако нямате акаунт — от линка за вход има бутон „Sign up“),
    прави форк на <a href="https://github.com/bulgariamitko/bg-izbori-monitor" target="_blank">хранилището</a>
    и стартира транскрипцията. Най-напред се обработват високорисковите
    секции (по данни на <a href="https://tibroish.bg/" target="_blank">tibroish.bg</a>),
    после средно-рисковите, после селата, малките и големите градове.
    Всяка готова транскрипция се качва автоматично като pull request и се
    обединява, ако премине проверката на схемата.
  </p>
</div>
<div class="disclaimer">
<strong>Важно:</strong> Това е автоматизиран инструмент, който сигнализира за
<em>възможни</em> нередности в аудиото от видеоизлъчването. Всеки сигнал —
особено „високо“ или „критично“ — трябва да бъде проверен ръчно от човек,
който гледа самото видео на посочения таймкод. Не публикувайте заключения
без първо да сте гледали видеото.
</div>
<div class="cards">
  <div class="card"><div class="n">{len(sections)}</div><div class="l">известни секции</div></div>
  <div class="card"><div class="n">{len(transcripts)}</div><div class="l">транскрибирани (от доброволци)</div></div>
  <div class="card"><div class="n">{len(findings_rows)}</div><div class="l">анализирани (от „оценителя“)</div></div>
  <div class="card"><div class="n">{max(0,len(transcripts)-len(findings_rows))}</div><div class="l">чакат анализ</div></div>
  <div class="card"><div class="n">{max(0,len(sections)-len(transcript_keys))}</div><div class="l">чакат транскрипция</div></div>
</div>
<div class="cards">
  <div class="card" style="border-top:3px solid #b00020"><div class="n">{high_done}/{high_total}</div><div class="l">високорискови секции (покрити)</div></div>
  <div class="card" style="border-top:3px solid #d98e0f"><div class="n">{mid_done}/{mid_total}</div><div class="l">средно-рискови секции (покрити)</div></div>
</div>
<div class="cards">"""]
    for s in SEV_ORDER:
        parts.append(f'<div class="card" style="border-top:3px solid {SEV_COLORS[s]}">'
                     f'<div class="n">{sev_counts[s]}</div><div class="l">{SEV_BG[s]}</div></div>')
    for k in ("clean","minor_concerns","serious_concerns"):
        parts.append(f'<div class="card"><div class="n"><span class="overall-dot" '
                     f'style="background:{OVERALL_COLORS[k]}"></span>{overall_counts[k]}</div>'
                     f'<div class="l">секции „{OVERALL_BG[k]}“</div></div>')
    parts.append("</div>")

    def _chunk_link(chunks: list[dict], video_url: str, ts: int) -> str:
        # Map global timestamp to the originating chunk + local offset. For
        # single-chunk sections (or when video_chunks is missing) just hash
        # the timestamp onto the main URL as before.
        if not chunks:
            return video_url + (f"#t={ts}" if ts else "")
        best = chunks[0]
        for c in chunks:
            if (c.get("start_sec") or 0) <= ts: best = c
            else: break
        offset = max(0, ts - (best.get("start_sec") or 0))
        return best["url"] + (f"#t={offset}" if offset else "")

    # findings for the CURRENT election — rendered client-side for sort + infinite scroll
    flat_js = []
    for x in flat:
        ts = int(x.get("timestamp_sec") or 0)
        vurl = _chunk_link(x.get("video_chunks") or [], x["video_url"], ts)
        flat_js.append({
            "sik": x["sik"],
            "severity": x.get("severity") or "info",
            "sev_rank": SEV_ORDER.index(x.get("severity")) if x.get("severity") in SEV_ORDER else 9,
            "ts": ts,
            "ts_fmt": _fmt_ts(ts),
            "summary": x.get("summary") or "",
            "detail":  x.get("detail") or "",
            "quote":   x.get("quote") or "",
            "category": x.get("category","other"),
            "category_bg": CAT_BG.get(x.get("category","other"), x.get("category","other")),
            "sev_bg": SEV_BG.get(x.get("severity"), x.get("severity")),
            "sev_color": SEV_COLORS.get(x.get("severity"), "#333"),
            "town": x.get("town") or "",
            "town_type": x.get("town_type") or "unknown",
            "region": x.get("region_name") or "",
            "address": x.get("address") or "",
            "vurl": vurl,
            "risk_tier": risk_tiers.get(x["sik"], ""),
        })

    sections_js = []
    for r in findings_rows:
        s = by_sik.get(r["sik"], {})
        r_chunks = r.get("video_chunks") or []
        sec_findings = []
        for f in r.get("findings", []):
            ts = int(f.get("timestamp_sec") or 0)
            sev = f.get("severity") or "info"
            sec_findings.append({
                "severity": sev,
                "sev_bg": SEV_BG.get(sev, sev),
                "sev_color": SEV_COLORS.get(sev, "#333"),
                "ts_fmt": _fmt_ts(ts),
                "ts": ts,
                "summary": f.get("summary") or "",
                "detail":  f.get("detail") or "",
                "quote":   f.get("quote") or "",
                "category_bg": CAT_BG.get(f.get("category","other"), f.get("category","other")),
                "vurl": _chunk_link(r_chunks, r["video_url"], ts),
            })
        sections_js.append({
            "sik": r["sik"],
            "region": r.get("region_name") or s.get("region_name") or "",
            "address": r.get("address") or s.get("address") or "",
            "town": r.get("town") or s.get("town") or "",
            "town_type": r.get("town_type") or s.get("town_type") or "unknown",
            "overall": r.get("overall") or "clean",
            "overall_bg": OVERALL_BG.get(r.get("overall"), r.get("overall","")),
            "overall_color": OVERALL_COLORS.get(r.get("overall","clean"), "#9ca3af"),
            "signal_count": len(r.get("findings", [])),
            "video_url": r["video_url"],
            "section_page": (s.get("oik_page","") + "#" + r["sik"]) if s.get("oik_page") else r["video_url"],
            "analyzed_at": r.get("analyzed_at",""),
            "risk_tier": risk_tiers.get(r["sik"], ""),
            "summary_bg": r.get("summary_bg","") or "",
            "findings": sec_findings,
        })

    parts.append(f'''<section>
<h2>Обработени секции (<span id="sections-count">{len(sections_js)}</span>)</h2>
<div class="controls">
  <label>Сортирай:
    <select id="sections-sort">
      <option value="analyzed">по време на анализ (ново→старо)</option>
      <option value="sik">по номер на СИК</option>
      <option value="town_type">по град / село</option>
      <option value="risk">по приоритет (риск)</option>
      <option value="overall">по оценка (най-лоши първо)</option>
      <option value="signals">по брой сигнали</option>
    </select>
  </label>
  <label>Тип място:
    <select id="sections-filter-town">
      <option value="">всички</option>
      <option value="village">само села</option>
      <option value="town">само малки градове</option>
      <option value="city">само големи градове</option>
    </select>
  </label>
</div>
<table><thead><tr><th style="width:28px"></th><th>СИК</th><th>Място</th><th>Тип</th><th>Приоритет</th>
<th>Обща оценка</th><th>Сигнали</th><th>Видео</th><th>Анализирано</th></tr></thead>
<tbody id="sections-tbody"></tbody></table>
<div id="sections-sentinel" style="padding:16px;text-align:center;color:#6b7280;font-size:13px"></div>
</section>''')

    parts.append(f'''<section>
<h2>Сигнали от {h(config.SLUG)} (<span id="findings-count">{len(flat_js)}</span>)</h2>
<div class="controls">
  <label>Сортирай:
    <select id="findings-sort">
      <option value="severity">по сериозност</option>
      <option value="sik">по номер на СИК</option>
      <option value="town_type">по град / село</option>
      <option value="risk">по приоритет (риск)</option>
    </select>
  </label>
  <label>Тип място:
    <select id="findings-filter-town">
      <option value="">всички</option>
      <option value="village">само села</option>
      <option value="town">само малки градове</option>
      <option value="city">само големи градове</option>
    </select>
  </label>
</div>
<div id="findings-list"></div>
<div id="findings-sentinel" style="padding:16px;text-align:center;color:#6b7280;font-size:13px"></div>
</section>''')

    parts.append(f'''<script>
const FINDINGS = {json.dumps(flat_js, ensure_ascii=False)};
const SECTIONS = {json.dumps(sections_js, ensure_ascii=False)};
const TTYPE_BG = {json.dumps(TTYPE_BG, ensure_ascii=False)};
const RISK_BG  = {{"high":"висок","mid":"среден","low":"нисък","":"—"}};
const RISK_RANK = {{"high":0,"mid":1,"low":2,"":3}};
const TTYPE_RANK = {{"village":0,"town":1,"city":2,"unknown":3}};
const BATCH = 40;

function esc(s){{return (s==null?"":String(s)).replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}})[c]);}}

function renderFinding(x){{
  const quote = x.quote ? `<div class="quote">«${{esc(x.quote)}}»</div>` : '';
  const tcls = ["village","town","city"].includes(x.town_type) ? x.town_type : "";
  const risk = x.risk_tier ? `<span class="tag risk-${{x.risk_tier}}">приоритет: ${{RISK_BG[x.risk_tier]}}</span>` : '';
  return `<div class="finding">
    <div><span class="sev" style="background:${{x.sev_color}}">${{esc(x.sev_bg)}}</span>
      <div class="meta">таймкод ${{esc(x.ts_fmt)}}</div></div>
    <div>
      <div><strong>${{esc(x.summary)}}</strong>
        <span class="tag">${{esc(x.category_bg)}}</span>
        <span class="tag ${{tcls}}">${{esc(x.town)}} · ${{esc(x.region)}}</span>
        ${{risk}}
      </div>
      <div style="font-size:13px;margin-top:4px">${{esc(x.detail)}}</div>
      ${{quote}}
      <div class="meta">
        <a href="${{esc(x.vurl)}}" target="_blank">▶ видео от ${{esc(x.ts_fmt)}}</a>
        · СИК <a href="#sik-${{esc(x.sik)}}">${{esc(x.sik)}}</a>
        · ${{esc(x.address)}}
      </div>
    </div></div>`;
}}

function renderSectionRow(r){{
  const tcls = ["village","town","city"].includes(r.town_type) ? r.town_type : "";
  const risk = r.risk_tier
    ? `<span class="tag risk-${{r.risk_tier}}">${{RISK_BG[r.risk_tier]}}</span>`
    : '<span style="color:#9ca3af">—</span>';
  const findingsList = (r.findings||[]).map((f,i)=>{{
    const quote = f.quote ? `<div class="quote" style="margin:4px 0 0 24px">«${{esc(f.quote)}}»</div>` : '';
    const detail = f.detail ? `<div style="margin:2px 0 0 24px;color:#4b5563">${{esc(f.detail)}}</div>` : '';
    return `<div style="margin-top:8px">
      <span class="sev" style="background:${{f.sev_color}}">${{esc(f.sev_bg)}}</span>
      <span class="meta" style="margin:0 6px">${{esc(f.ts_fmt)}}</span>
      <span class="tag">${{esc(f.category_bg)}}</span>
      <strong style="margin-left:6px">${{esc(f.summary)}}</strong>
      ${{detail}}${{quote}}
      <div class="meta" style="margin:2px 0 0 24px"><a href="${{esc(f.vurl)}}" target="_blank">▶ видео от ${{esc(f.ts_fmt)}}</a></div>
    </div>`;
  }}).join("");
  const hasRecap = r.summary_bg || (r.findings||[]).length;
  const caret = hasRecap
    ? `<span class="caret" style="display:inline-block;width:14px;color:#6b7280;cursor:pointer;user-select:none">▸</span>`
    : '';
  const recap = hasRecap
    ? `<tr class="recap-row" style="display:none"><td colspan="9" style="padding:10px 14px 16px;font-size:13px;color:#374151;background:#fafafa;border-top:0">
        ${{r.summary_bg ? `<div><strong style="color:#6b7280">Кратко:</strong> ${{esc(r.summary_bg)}}</div>` : ''}}
        ${{findingsList}}
       </td></tr>`
    : '';
  const clickable = hasRecap ? 'cursor:pointer' : '';
  return `<tr id="sik-${{esc(r.sik)}}" class="section-row" data-has-recap="${{hasRecap?1:0}}" style="${{clickable}}">
    <td style="text-align:center">${{caret}}</td>
    <td>${{esc(r.sik)}}</td>
    <td>${{esc(r.region)}} — ${{esc(r.address)}}</td>
    <td><span class="tag ${{tcls}}">${{esc(TTYPE_BG[r.town_type]||'—')}}</span></td>
    <td>${{risk}}</td>
    <td><span class="overall-dot" style="background:${{r.overall_color}}"></span>${{esc(r.overall_bg)}}</td>
    <td>${{r.signal_count}}</td>
    <td><a href="${{esc(r.section_page)}}" target="_blank">гледай</a></td>
    <td style="font-size:12px;color:#6b7280">${{esc(r.analyzed_at)}}</td></tr>${{recap}}`;
}}

function sortFindings(arr, mode){{
  const a = arr.slice();
  if(mode==="severity") a.sort((x,y)=> x.sev_rank-y.sev_rank || y.ts-x.ts);
  else if(mode==="sik") a.sort((x,y)=> x.sik.localeCompare(y.sik));
  else if(mode==="town_type") a.sort((x,y)=> (TTYPE_RANK[x.town_type]??9)-(TTYPE_RANK[y.town_type]??9) || x.sik.localeCompare(y.sik));
  else if(mode==="risk") a.sort((x,y)=> (RISK_RANK[x.risk_tier]??9)-(RISK_RANK[y.risk_tier]??9) || x.sev_rank-y.sev_rank);
  return a;
}}

function sortSections(arr, mode){{
  const a = arr.slice();
  const OV_RANK = {{"serious_concerns":0,"minor_concerns":1,"clean":2}};
  if(mode==="analyzed") a.sort((x,y)=> (y.analyzed_at||"").localeCompare(x.analyzed_at||""));
  else if(mode==="sik") a.sort((x,y)=> x.sik.localeCompare(y.sik));
  else if(mode==="town_type") a.sort((x,y)=> (TTYPE_RANK[x.town_type]??9)-(TTYPE_RANK[y.town_type]??9) || x.sik.localeCompare(y.sik));
  else if(mode==="risk") a.sort((x,y)=> (RISK_RANK[x.risk_tier]??9)-(RISK_RANK[y.risk_tier]??9) || x.sik.localeCompare(y.sik));
  else if(mode==="overall") a.sort((x,y)=> (OV_RANK[x.overall]??9)-(OV_RANK[y.overall]??9) || y.signal_count-x.signal_count);
  else if(mode==="signals") a.sort((x,y)=> y.signal_count-x.signal_count);
  return a;
}}

function makeInfinite(opts){{
  let data = [], rendered = 0;
  const container = document.getElementById(opts.containerId);
  const sentinel  = document.getElementById(opts.sentinelId);
  const countEl   = document.getElementById(opts.countId);
  function paint(){{
    const end = Math.min(rendered + BATCH, data.length);
    const chunk = data.slice(rendered, end).map(opts.render).join("");
    if(opts.tbody) container.insertAdjacentHTML("beforeend", chunk);
    else container.insertAdjacentHTML("beforeend", chunk);
    rendered = end;
    sentinel.textContent = rendered >= data.length
      ? (data.length ? "— край —" : "няма резултати")
      : `показани ${{rendered}} от ${{data.length}} · скролни за още`;
  }}
  function reset(newData){{
    data = newData; rendered = 0;
    container.innerHTML = "";
    countEl.textContent = data.length;
    paint();
  }}
  const io = new IntersectionObserver(entries=>{{
    for(const e of entries){{ if(e.isIntersecting && rendered < data.length) paint(); }}
  }}, {{rootMargin:"400px"}});
  io.observe(sentinel);
  return {{reset}};
}}

const findingsScroller = makeInfinite({{
  containerId:"findings-list", sentinelId:"findings-sentinel",
  countId:"findings-count", render:renderFinding
}});
const sectionsScroller = makeInfinite({{
  containerId:"sections-tbody", sentinelId:"sections-sentinel",
  countId:"sections-count", render:renderSectionRow, tbody:true
}});

function refreshFindings(){{
  const sort = document.getElementById("findings-sort").value;
  const filt = document.getElementById("findings-filter-town").value;
  let d = FINDINGS;
  if(filt) d = d.filter(x=> x.town_type===filt);
  findingsScroller.reset(sortFindings(d, sort));
}}
function refreshSections(){{
  const sort = document.getElementById("sections-sort").value;
  const filt = document.getElementById("sections-filter-town").value;
  let d = SECTIONS;
  if(filt) d = d.filter(x=> x.town_type===filt);
  sectionsScroller.reset(sortSections(d, sort));
}}
document.getElementById("findings-sort").addEventListener("change", refreshFindings);
document.getElementById("findings-filter-town").addEventListener("change", refreshFindings);
document.getElementById("sections-sort").addEventListener("change", refreshSections);
document.getElementById("sections-filter-town").addEventListener("change", refreshSections);
document.getElementById("sections-tbody").addEventListener("click", e=>{{
  // Don't swallow clicks on the "гледай" link
  if(e.target.closest("a")) return;
  const row = e.target.closest("tr.section-row");
  if(!row || row.dataset.hasRecap !== "1") return;
  const recap = row.nextElementSibling;
  if(!recap || !recap.classList.contains("recap-row")) return;
  const open = recap.style.display !== "none";
  recap.style.display = open ? "none" : "";
  const caret = row.querySelector(".caret");
  if(caret) caret.textContent = open ? "▸" : "▾";
}});
refreshFindings();
refreshSections();
</script>''')

    parts.append(f'''<footer>
  Генерирано от <a href="https://github.com/bulgariamitko/bg-izbori-monitor">bg-izbori-monitor</a>
  · инструмент за гражданско наблюдение, не официално заключение.
</footer></main></body></html>''')

    out = config.DASHBOARD_HTML
    out.write_text("".join(parts), encoding="utf-8")
    print(f"[dashboard] -> {out}  ({len(flat)} findings across {len(findings_rows)} sections)")

if __name__ == "__main__":
    build()
