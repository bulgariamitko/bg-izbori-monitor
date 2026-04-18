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
    transcripts= list(store.iter_transcripts())
    findings_rows = list(store.iter_findings())
    finding_keys = {(f["sik"], f["tour"]) for f in findings_rows}
    transcript_keys = {(t["sik"], t["tour"]) for t in transcripts}

    # flatten finding entries
    flat = []
    for f in findings_rows:
        for item in f.get("findings", []):
            flat.append({**item,
                "sik": f["sik"], "tour": f["tour"],
                "video_url": f["video_url"],
                "region_name": f.get("region_name") or by_sik.get(f["sik"],{}).get("region_name"),
                "town": f.get("town") or by_sik.get(f["sik"],{}).get("town"),
                "town_type": f.get("town_type") or by_sik.get(f["sik"],{}).get("town_type"),
                "address": f.get("address") or by_sik.get(f["sik"],{}).get("address"),
                "overall": f.get("overall"),
            })
    sev_rank = {s:i for i,s in enumerate(SEV_ORDER)}
    flat.sort(key=lambda x: (sev_rank.get(x.get("severity"),9), -float(x.get("timestamp_sec") or 0)))

    sev_counts = {s:0 for s in SEV_ORDER}
    for x in flat: sev_counts[x.get("severity","info")] = sev_counts.get(x.get("severity","info"),0)+1

    overall_counts = {"clean":0,"minor_concerns":0,"serious_concerns":0}
    for f in findings_rows: overall_counts[f.get("overall","clean")] = overall_counts.get(f.get("overall","clean"),0)+1

    contribs = {}
    for t in transcripts:
        k = (t.get("contributed_by") or "анонимен").strip() or "анонимен"
        contribs[k] = contribs.get(k,0) + 1

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
.overall-dot{{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:6px;vertical-align:middle}}
footer{{text-align:center;color:#6b7280;font-size:12px;padding:24px}}
</style></head><body>
<header>
  <h1>БГ Избори · видеонаблюдение на СИК ({h(config.SLUG)})</h1>
  <div class="sub">разпределен граждански преглед · обновено {h(now)}
    · <a href="https://github.com/bulgariamitko/bg-izbori-monitor" style="color:#9cf">код</a></div>
</header>
<main>
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
<div class="cards">"""]
    for s in SEV_ORDER:
        parts.append(f'<div class="card" style="border-top:3px solid {SEV_COLORS[s]}">'
                     f'<div class="n">{sev_counts[s]}</div><div class="l">{SEV_BG[s]}</div></div>')
    for k in ("clean","minor_concerns","serious_concerns"):
        parts.append(f'<div class="card"><div class="n"><span class="overall-dot" '
                     f'style="background:{OVERALL_COLORS[k]}"></span>{overall_counts[k]}</div>'
                     f'<div class="l">секции „{OVERALL_BG[k]}“</div></div>')
    parts.append("</div>")

    # findings
    parts.append(f'<section><h2>Сигнали ({len(flat)})</h2>')
    if not flat: parts.append('<div style="padding:24px;color:#6b7280">Все още няма сигнали.</div>')
    for x in flat:
        ts = _fmt_ts(x.get("timestamp_sec"))
        vurl = x["video_url"] + (f"#t={int(x.get('timestamp_sec') or 0)}" if x.get("timestamp_sec") else "")
        tcls = x.get("town_type") if x.get("town_type") in ("village","town","city") else ""
        parts.append(f'''<div class="finding">
          <div><span class="sev" style="background:{SEV_COLORS.get(x.get("severity"),"#333")}">{h(SEV_BG.get(x.get("severity"),x.get("severity")))}</span>
               <div class="meta">таймкод {h(ts)}</div></div>
          <div>
            <div><strong>{h(x.get("summary"))}</strong>
                 <span class="tag">{h(CAT_BG.get(x.get("category","other"), x.get("category","other")))}</span>
                 <span class="tag {tcls}">{h(x.get("town") or "")} · {h(x.get("region_name") or "")}</span>
            </div>
            <div style="font-size:13px;margin-top:4px">{h(x.get("detail"))}</div>
            {'<div class="quote">«'+h(x.get("quote"))+'»</div>' if x.get("quote") else ''}
            <div class="meta">
              <a href="{h(vurl)}" target="_blank">▶ видео от {h(ts)}</a>
              · СИК <a href="#sik-{h(x["sik"])}">{h(x["sik"])}</a>
              · {h(x.get("address") or "")}
            </div>
          </div></div>''')
    parts.append('</section>')

    # processed sections table
    rows = sorted(findings_rows, key=lambda r: r.get("analyzed_at") or "", reverse=True)
    parts.append(f'<section><h2>Обработени секции ({len(rows)})</h2><table>'
                 '<thead><tr><th>СИК</th><th>Място</th><th>Обща оценка</th>'
                 '<th>Сигнали</th><th>Видео</th><th>Анализирано</th></tr></thead><tbody>')
    for r in rows[:400]:
        parts.append(f'''<tr id="sik-{h(r["sik"])}">
          <td>{h(r["sik"])}</td>
          <td>{h(r.get("region_name") or "")} — {h(r.get("address") or "")}</td>
          <td><span class="overall-dot" style="background:{OVERALL_COLORS.get(r.get("overall","clean"),"#9ca3af")}"></span>
              {h(OVERALL_BG.get(r.get("overall"), r.get("overall","")))}</td>
          <td>{len(r.get("findings",[]))}</td>
          <td><a href="{h(r["video_url"])}" target="_blank">гледай</a></td>
          <td style="font-size:12px;color:#6b7280">{h(r.get("analyzed_at",""))}</td></tr>''')
    parts.append('</tbody></table></section>')

    # leaderboard
    if contribs:
        parts.append('<section><h2>Доброволци (по брой транскрипции)</h2><table>'
                     '<thead><tr><th>Доброволец</th><th>Транскрипции</th></tr></thead><tbody>')
        for name, n in sorted(contribs.items(), key=lambda x: -x[1])[:50]:
            parts.append(f'<tr><td>{h(name)}</td><td>{n}</td></tr>')
        parts.append('</tbody></table></section>')

    parts.append(f'''<footer>
  Генерирано от <a href="https://github.com/bulgariamitko/bg-izbori-monitor">bg-izbori-monitor</a>
  · инструмент за гражданско наблюдение, не официално заключение.
</footer></main></body></html>''')

    out = config.DASHBOARD_HTML
    out.write_text("".join(parts), encoding="utf-8")
    print(f"[dashboard] -> {out}  ({len(flat)} findings across {len(findings_rows)} sections)")

if __name__ == "__main__":
    build()
