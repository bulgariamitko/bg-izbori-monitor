"""Generate a static dashboard.html from bg_izbori.db.

Groups findings by severity and by section; each finding links to the video at
the right timestamp (using t=HHMMSS fragment; users can jump there after opening).
"""
from __future__ import annotations
import html, json
from datetime import datetime
from pathlib import Path

import db, config

SEV_ORDER = ["critical", "high", "medium", "low", "info"]
SEV_COLORS = {
    "critical": "#b00020", "high": "#d9480f", "medium": "#d98e0f",
    "low": "#6b7280", "info": "#9ca3af",
}
SEV_BG = {
    "critical": "критично",
    "high":     "високо",
    "medium":   "средно",
    "low":      "ниско",
    "info":     "инфо",
}
CAT_BG = {
    "tampering":     "манипулация",
    "miscounting":   "грешно броене",
    "protocol":      "протокол",
    "intimidation":  "заплахи",
    "unauthorized":  "неуп. лица",
    "procedure":     "процедура",
    "dispute":       "спор",
    "other":         "друго",
}
TOWN_TYPE_BG = {"village": "село", "town": "град (малък)", "city": "голям град", "unknown": "—"}
STATUS_BG = {
    "pending":      "чака",
    "downloading":  "сваляне",
    "downloaded":   "свалено",
    "transcribing": "транскрипция",
    "transcribed":  "транскрибирано",
    "analyzing":    "анализ",
    "analyzed":     "анализирано",
    "failed":       "грешка",
}

def _fmt_ts(s: float | None) -> str:
    if not s: return ""
    s = int(s); return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def build():
    config.PROMPT_PATH  # ensure path exists
    db.init()

    sev_counts = {s: db.fetchone(
        "SELECT COUNT(*) c FROM findings WHERE severity=?", s)["c"] for s in SEV_ORDER}
    totals = db.fetchone("""SELECT
        COUNT(*) total,
        SUM(status='analyzed') analyzed,
        SUM(status='failed')   failed,
        SUM(status='pending')  pending,
        SUM(status IN ('downloading','downloaded','transcribing','transcribed','analyzing')) in_flight
        FROM videos""") or {}
    sec_totals = db.fetchone("SELECT COUNT(*) c FROM sections WHERE slug=?", config.SLUG)["c"]

    findings = db.fetchall("""
        SELECT f.*, v.sik, v.tour, v.video_url, v.duration_sec,
               s.region_name, s.address, s.town, s.town_type
        FROM findings f
        JOIN videos v ON v.id = f.video_id
        JOIN sections s USING(sik)
        ORDER BY CASE f.severity
                    WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2   WHEN 'low'  THEN 3
                    ELSE 4 END, f.created_at DESC
    """)

    analyzed = db.fetchall("""
        SELECT v.id, v.sik, v.tour, v.status, v.duration_sec, v.video_url,
               v.analyzed_at,
               s.region_name, s.address, s.town, s.town_type,
               (SELECT COUNT(*) FROM findings WHERE video_id=v.id) findings
        FROM videos v JOIN sections s USING(sik)
        WHERE v.status IN ('analyzed','failed')
        ORDER BY v.analyzed_at DESC LIMIT 200
    """)

    def h(x): return html.escape(str(x or ""))

    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="bg"><head>
<meta charset="utf-8">
<title>БГ Избори — {config.SLUG}</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;margin:0;background:#f7f7f8;color:#111}}
header{{background:#111;color:#fff;padding:16px 24px}}
header h1{{margin:0;font-size:20px}}
header .sub{{font-size:13px;opacity:.75;margin-top:4px}}
main{{max-width:1200px;margin:0 auto;padding:24px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px}}
.card .n{{font-size:22px;font-weight:600}}
.card .l{{font-size:12px;color:#6b7280;letter-spacing:.02em}}
section{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:24px;overflow:hidden}}
section h2{{margin:0;padding:12px 16px;font-size:15px;background:#fafafa;border-bottom:1px solid #eee}}
.finding{{padding:12px 16px;border-bottom:1px solid #f1f1f1;display:grid;grid-template-columns:110px 1fr;gap:12px}}
.finding:last-child{{border-bottom:none}}
.sev{{font-size:11px;text-transform:uppercase;font-weight:700;color:#fff;padding:2px 8px;border-radius:4px;display:inline-block;align-self:start}}
.meta{{color:#6b7280;font-size:12px;margin-top:4px}}
.quote{{background:#fff7ed;border-left:3px solid #f59e0b;padding:6px 10px;margin-top:6px;font-size:13px;font-style:italic}}
a{{color:#2563eb;text-decoration:none}} a:hover{{text-decoration:underline}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:8px 12px;border-bottom:1px solid #f1f1f1;text-align:left}}
th{{background:#fafafa;font-weight:600;font-size:12px;color:#6b7280}}
tr.failed td{{color:#b00020}}
.tag{{font-size:11px;padding:2px 6px;border-radius:4px;background:#eef2ff;color:#3730a3;margin-left:6px}}
.village{{background:#dcfce7;color:#14532d}}
.town{{background:#e0f2fe;color:#075985}}
.city{{background:#fef3c7;color:#78350f}}
.disclaimer{{background:#fff8e1;border:1px solid #f5d97b;padding:12px 16px;border-radius:8px;margin-bottom:24px;font-size:13px}}
</style></head><body>
<header>
  <h1>БГ Избори — видеонаблюдение на СИК ({h(config.SLUG)})</h1>
  <div class="sub">автоматичен преглед на преброяването · обновено {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>
</header>
<main>
  <div class="disclaimer">
    <strong>Важно:</strong> Това е автоматизиран инструмент, който сигнализира за
    <em>възможни</em> нередности в аудиото от видеоизлъчването. Всеки сигнал —
    особено с ниво „високо“ или „критично“ — трябва да бъде проверен ръчно
    от човек, който гледа самото видео на посочения таймкод, преди да се
    прави публично заключение.
  </div>
  <div class="cards">
    <div class="card"><div class="n">{sec_totals}</div><div class="l">известни секции</div></div>
    <div class="card"><div class="n">{totals.get('total',0) or 0}</div><div class="l">видеа общо</div></div>
    <div class="card"><div class="n">{totals.get('analyzed',0) or 0}</div><div class="l">анализирани</div></div>
    <div class="card"><div class="n">{totals.get('in_flight',0) or 0}</div><div class="l">в процес</div></div>
    <div class="card"><div class="n">{totals.get('pending',0) or 0}</div><div class="l">чакат</div></div>
    <div class="card"><div class="n" style="color:#b00020">{totals.get('failed',0) or 0}</div><div class="l">с грешка</div></div>
  </div>
  <div class="cards">""")
    for s in SEV_ORDER:
        parts.append(f"""<div class="card" style="border-top:3px solid {SEV_COLORS[s]}">
          <div class="n">{sev_counts[s]}</div><div class="l">{SEV_BG[s]}</div></div>""")
    parts.append("</div>")

    # findings
    parts.append(f"<section><h2>Сигнали ({len(findings)})</h2>")
    if not findings:
        parts.append('<div style="padding:24px;color:#6b7280">Все още няма сигнали.</div>')
    for f in findings:
        ts = _fmt_ts(f["timestamp_sec"])
        url = f["video_url"] + ("#t=" + str(int(f["timestamp_sec"])) if f["timestamp_sec"] else "")
        tag_cls = f['town_type'] if f['town_type'] in ('village','town','city') else ''
        parts.append(f"""<div class="finding">
            <div><span class="sev" style="background:{SEV_COLORS.get(f['severity'],'#333')}">{h(SEV_BG.get(f['severity'], f['severity']))}</span>
                 <div class="meta">таймкод {h(ts)}</div></div>
            <div>
              <div><strong>{h(f['summary'])}</strong>
                 <span class="tag">{h(CAT_BG.get(f['category'] or 'other', f['category'] or 'other'))}</span>
                 <span class="tag {tag_cls}">{h(f['town'] or '')} · {h(f['region_name'])}</span>
              </div>
              <div style="font-size:13px;margin-top:4px">{h(f['detail'])}</div>
              {'<div class="quote">«'+h(f['quote'])+'»</div>' if f['quote'] else ''}
              <div class="meta">
                <a href="{h(url)}" target="_blank">▶ видео от {h(ts or '0')}</a>
                · СИК <a href="#sik-{h(f['sik'])}">{h(f['sik'])}</a>
                · {h(f['address'])}
              </div>
            </div>
          </div>""")
    parts.append("</section>")

    # recent processed
    parts.append(f"<section><h2>Последно обработени секции ({len(analyzed)})</h2><table>"
                 f"<thead><tr><th>СИК</th><th>Място</th><th>Статус</th><th>Продълж.</th>"
                 f"<th>Сигнали</th><th>Видео</th></tr></thead><tbody>")
    for r in analyzed:
        cls = "failed" if r["status"]=="failed" else ""
        parts.append(f"""<tr id="sik-{h(r['sik'])}" class="{cls}">
           <td>{h(r['sik'])}</td>
           <td>{h(r['region_name'])} — {h(r['address'])}</td>
           <td>{h(STATUS_BG.get(r['status'], r['status']))}</td>
           <td>{_fmt_ts(r['duration_sec'])}</td>
           <td>{h(r['findings'])}</td>
           <td><a href="{h(r['video_url'])}" target="_blank">гледай</a></td>
           </tr>""")
    parts.append("""</tbody></table></section>
  <footer style="text-align:center;color:#6b7280;font-size:12px;padding:24px">
    Генерирано локално от BG Izbori · код: github (TBD) · инструмент за
    гражданско наблюдение, не официално заключение.
  </footer>
</main></body></html>""")

    out = config.DASHBOARD_HTML
    out.write_text("".join(parts), encoding="utf-8")
    print(f"[dashboard] -> {out}  ({len(findings)} findings)")

if __name__ == "__main__":
    build()
