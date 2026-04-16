"""
NRC Market Intelligence Scraper
- Scrapes headlines from 11 CRE sources
- Claude picks the 10 most relevant articles and writes a summary for each
- Generates a clean dashboard with headlines + summaries + source links
- Fast, cheap, no full article fetching
"""

import json, os, re, time, hashlib, requests
from datetime import datetime, timezone
from pathlib import Path
import anthropic

# ─────────────────────────────────────────────────────────────────
# NEWS SEARCH QUERIES — edit freely
# NewsAPI fetches from Bisnow, CoStar, WSJ, Globe, Real Deal etc.
# ─────────────────────────────────────────────────────────────────
NEWS_QUERIES = [
    "commercial real estate Boston",
    "industrial real estate Boston Pittsburgh",
    "life science real estate Boston",
    "office real estate CMBS distressed 2026",
    "cold storage real estate Northeast",
    "multifamily residential Boston New York",
    "real estate private equity acquisition 2026",
    "CRE cap rate interest rate 2026",
    "Boston real estate lease sale development",
    "Pittsburgh California real estate 2026",
]

# ─────────────────────────────────────────────────────────────────
# PROMPT — edit freely
# ─────────────────────────────────────────────────────────────────
RANKING_PROMPT = """
You are a senior research analyst at North River Company (NRC), a real estate private equity firm based in Boston.

NRC focus:
- Markets: Boston, New York, Maine, Pittsburgh, California
- Asset classes: industrial, life science, Class B office, cold storage, tower residential (100+ units)
- Strategy: acquisitions, asset management, value-add, opportunistic, core/core-plus
- Also: cap rates, interest rates, CMBS, private credit, CRE trends, lease signings, distressed assets

From the headlines below, return this exact JSON (no markdown, no commentary):
{
  "articles": [
    {
      "title": "exact headline",
      "url": "exact url",
      "source": "exact source",
      "summary": "2-sentence summary of what this means for NRC",
      "sentiment": "bullish | bearish | neutral",
      "market": "Boston | New York | Pittsburgh | California | Maine | National",
      "asset_class": "Industrial | Life Science | Office | Cold Storage | Multifamily | Capital Markets",
      "data_point": "specific figure from headline e.g. $134M or 7.6% vacancy, or null"
    }
  ],
  "market_snapshot": [
    {
      "label": "short label e.g. Boston Industrial Vacancy",
      "value": "the number e.g. 7.6%",
      "note": "one short context note",
      "trend": "up | down | flat"
    }
  ],
  "notable_transactions": [
    {
      "address": "property address or name",
      "detail": "deal detail e.g. $134M sale or 231K SF lease",
      "tenant_buyer": "tenant or buyer name if mentioned, else null",
      "type": "Sale | Lease | Development | Financing"
    }
  ]
}

Pick the 10 most relevant articles ordered by relevance. Include up to 4 market_snapshot stats and up to 6 notable_transactions pulled from the headlines.
"""

ROOT         = Path(__file__).parent.parent
OUTPUT_FILE  = ROOT / "docs" / "index.html"
ARCHIVE_FILE = ROOT / "docs" / "data" / "archive.json"


# ─────────────────────────────────────────────────────────────────
# NEWSAPI FETCHING
# ─────────────────────────────────────────────────────────────────
def fetch_headlines_newsapi(api_key):
    """Fetch headlines from NewsAPI — works from GitHub Actions, no blocking."""
    from datetime import timedelta
    headers = {"X-Api-Key": api_key}
    all_articles = []
    seen_urls = set()
    # Only fetch last 3 days
    from_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")

    for query in NEWS_QUERIES:
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "from": from_date,
                    "pageSize": 20,
                    "domains": "bisnow.com,globest.com,commercialobserver.com,therealdeal.com,costar.com,wsj.com,bizjournals.com,bostonglobe.com,nytimes.com,crainsnewyork.com,credaily.com,propmodo.com,connect.media,rebusinessonline.com,multihousingnews.com,nerej.com"
                },
                headers=headers,
                timeout=15
            )
            if r.status_code == 200:
                data = r.json()
                articles = data.get("articles", [])
                for a in articles:
                    url = a.get("url","")
                    title = a.get("title","") or ""
                    source = a.get("source",{}).get("name","Unknown")
                    if url and url not in seen_urls and len(title) > 20 and "[Removed]" not in title:
                        seen_urls.add(url)
                        all_articles.append({"title": title, "url": url, "source": source})
                print(f"  [{query[:40]}] {len(articles)} articles")
            else:
                print(f"  [{query[:40]}] Error {r.status_code}: {r.text[:80]}")
            time.sleep(0.5)
        except Exception as e:
            print(f"  [{query[:40]}] Exception: {e}")

    print(f"\nTotal unique headlines: {len(all_articles)}")
    return all_articles


# ─────────────────────────────────────────────────────────────────
# CLAUDE — one call, returns top 10 with summaries
# ─────────────────────────────────────────────────────────────────
def rank_with_claude(client, all_headlines):
    headline_list = [{"title": a["title"], "url": a["url"], "source": a["source"]} for a in all_headlines]

    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": f"{RANKING_PROMPT}\n\nHeadlines:\n{json.dumps(headline_list, indent=2)}"
        }]
    )

    raw = re.sub(r"^```json|^```|```$", "", msg.content[0].text.strip(), flags=re.MULTILINE).strip()
    data = json.loads(raw)
    articles = data.get("articles", data) if isinstance(data, dict) else data
    snapshot = data.get("market_snapshot", []) if isinstance(data, dict) else []
    transactions = data.get("notable_transactions", []) if isinstance(data, dict) else []
    print(f"  Claude returned {len(articles)} articles, {len(snapshot)} stats, {len(transactions)} transactions")
    return articles, snapshot, transactions


# ─────────────────────────────────────────────────────────────────
# ARCHIVE
# ─────────────────────────────────────────────────────────────────
def load_archive():
    ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if ARCHIVE_FILE.exists():
        with open(ARCHIVE_FILE) as f: return json.load(f)
    return []

def save_archive(articles):
    with open(ARCHIVE_FILE, "w") as f: json.dump(articles, f, indent=2)


# ─────────────────────────────────────────────────────────────────
# HTML DASHBOARD
# ─────────────────────────────────────────────────────────────────
def sc(s): return {"bullish":"#1e6e4a","bearish":"#b53325","neutral":"#2660a4"}.get(s or "neutral","#2660a4")
def sb(s): return {"bullish":"rgba(30,110,74,0.1)","bearish":"rgba(181,51,37,0.1)","neutral":"rgba(38,96,164,0.1)"}.get(s or "neutral","rgba(38,96,164,0.1)")
def sl(s): return {"bullish":"#e8f5f0","bearish":"#fdf0ee","neutral":"#eef3fb"}.get(s or "neutral","#eef3fb")

def esc(s):
    if not s: return ""
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def article_card(a, rank, is_today=True):
    sent = a.get("sentiment") or "neutral"
    date_str = a.get("date","")
    badge = '<span class="badge-today">TODAY</span>' if is_today else f'<span class="badge-date">{date_str}</span>'

    return f"""<a class="acard" href="{a['url']}" target="_blank" data-sentiment="{sent}">
  <div class="acard-rank">{rank}</div>
  <div class="acard-content">
    <div class="acard-meta">
      <span class="acard-source">{esc(a['source'])}</span>
      {badge}
      <span class="sent-pill" style="color:{sc(sent)};background:{sb(sent)}">{sent.upper()}</span>
    </div>
    <div class="acard-title">{esc(a['title'])}</div>
    <div class="acard-summary">{esc(a.get('summary',''))}</div>
  </div>
  <div class="acard-arrow">→</div>
</a>"""


def archive_rows_html(archive):
    rows = ""
    for a in archive:
        sent = a.get("sentiment","neutral")
        rows += f"""<tr>
      <td class="td-mono">{esc(a.get("date",""))}</td>
      <td class="td-src">{esc(a.get("source",""))}</td>
      <td><a href="{a['url']}" target="_blank" class="arc-link">{esc(a['title'])}</a></td>
      <td class="td-sum">{esc(a.get('summary',''))}</td>
      <td><span class="sent-pill" style="color:{sc(sent)};background:{sb(sent)}">{sent.upper()}</span></td>
    </tr>"""
    return rows


def esc(s):
    if not s: return ""
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def market_badge(m):
    colors = {"Boston":"#1a3a5c","New York":"#2d4a7a","Pittsburgh":"#3a5a2a","California":"#5a3a1a","Maine":"#3a2a5a","National":"#4a4a4a"}
    m = (m or "").split("/")[0].split(",")[0].strip()
    c = colors.get(m, "#4a4a4a")
    return f'<span class="mbadge" style="background:{c}">{esc(m)}</span>'

def asset_tag(a):
    colors = {"Industrial":"#1e4d2b","Life Science":"#1a3a5c","Office":"#4a3a1a","Cold Storage":"#1a4a4a","Multifamily":"#3a1a4a","Capital Markets":"#4a1a1a"}
    c = colors.get(a or "", "#444")
    return f'<span class="abadge" style="background:{c}">{esc(a)}</span>' if a else ""

def trend_icon(t):
    return {"up":"↑","down":"↓","flat":"→"}.get(t or "flat","→")

def trend_color(t):
    return {"up":"#1e6e4a","down":"#b53325","flat":"#8492a8"}.get(t or "flat","#8492a8")

def sent_color(s):
    return {"bullish":"#1e6e4a","bearish":"#b53325","neutral":"#2660a4"}.get(s or "neutral","#2660a4")

def sent_bg(s):
    return {"bullish":"#eef7f2","bearish":"#fdf0ee","neutral":"#eef3fb"}.get(s or "neutral","#eef3fb")

def generate_html(today, archive, run_date, snapshot=None, transactions=None):
    snapshot = snapshot or []
    transactions = transactions or []
    fdate = datetime.strptime(run_date,"%Y-%m-%d").strftime("%B %d, %Y")
    bullish = sum(1 for a in today if a.get("sentiment")=="bullish")
    bearish = sum(1 for a in today if a.get("sentiment")=="bearish")

    # ── STAT CARDS ──
    stat_cards = ""
    for s in snapshot[:4]:
        tc = trend_color(s.get("trend"))
        ti = trend_icon(s.get("trend"))
        stat_cards += f"""<div class="stat-card">
  <div class="stat-label">{esc(s.get('label',''))}</div>
  <div class="stat-value">{esc(s.get('value',''))}</div>
  <div class="stat-note" style="color:{tc}">{ti} {esc(s.get('note',''))}</div>
</div>"""

    # ── HEADLINE ROWS — only show articles from today ──
    from datetime import date
    today_date = date.today().isoformat()
    today_only = [a for a in today if a.get("date","") == today_date]
    if not today_only:
        today_only = today  # fallback to all if date mismatch
    headline_rows = ""
    for a in today_only:
        sc = sent_color(a.get("sentiment"))
        sb = sent_bg(a.get("sentiment"))
        dp = f'<span class="data-point">{esc(a.get("data_point",""))}</span>' if a.get("data_point") else ""
        headline_rows += f"""<a class="hl-row" href="{esc(a['url'])}" target="_blank">
  <div class="hl-left">
    {market_badge(a.get('market',''))}
    <div class="hl-text">
      <div class="hl-title">{esc(a['title'])}{dp}</div>
      <div class="hl-sub">{esc(a.get('asset_class',''))} · {esc(a.get('source',''))}</div>
    </div>
  </div>
  <div class="hl-right">
    <span class="sent-dot" style="background:{sc}" title="{a.get('sentiment','')}"></span>
  </div>
</a>"""

    # ── SUMMARY CARDS (right panel) ──
    signal_cards = ""
    for a in today[:5]:
        sc2 = sent_color(a.get("sentiment"))
        icon = {"bullish":"↑","bearish":"↓","neutral":"i"}.get(a.get("sentiment","neutral"),"i")
        signal_cards += f"""<div class="signal-card">
  <div class="signal-icon" style="background:{sc2}">{icon}</div>
  <div class="signal-body">
    <div class="signal-summary">{esc(a.get('summary',''))}</div>
    <div class="signal-source">{esc(a.get('source',''))}</div>
  </div>
</div>"""

    # ── TRANSACTIONS ──
    tx_cells = ""
    for tx in transactions[:6]:
        tx_cells += f"""<div class="tx-cell">
  <div class="tx-addr">{esc(tx.get('address',''))}</div>
  <div class="tx-detail">{esc(tx.get('detail',''))}</div>
  <div class="tx-who">{esc(tx.get('tenant_buyer') or tx.get('type',''))}</div>
</div>"""

    # ── ARCHIVE ROWS ──
    arc_rows = ""
    for a in archive:
        sc3 = sent_color(a.get("sentiment","neutral"))
        sb3 = sent_bg(a.get("sentiment","neutral"))
        arc_rows += f"""<tr>
  <td class="td-date">{esc(a.get('date',''))}</td>
  <td>{market_badge(a.get('market',''))}</td>
  <td><a href="{esc(a['url'])}" target="_blank" class="arc-link">{esc(a['title'])}</a></td>
  <td class="td-sum">{esc(a.get('summary',''))}</td>
  <td><span class="sent-pill" style="color:{sc3};background:{sb3}">{(a.get('sentiment') or '—').upper()}</span></td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NRC Market Intelligence — {fdate}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{
  --navy:#0d1c2e;--navy2:#1a2e44;
  --blue:#1a3a5c;--bluel:#2d5f8a;
  --w:#ffffff;--off:#f8f9fb;--off2:#f2f4f7;
  --g1:#e8ecf2;--g2:#d0d6e0;--g3:#b0bac8;--g4:#7a8898;--g6:#3a4858;
  --green:#1e5c3a;--greenl:#2a7d50;--red:#8b2315;--redl:#b53325;
  --border:#e2e6ed;
  --font:'Inter',system-ui,sans-serif;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:var(--font);background:var(--off);color:var(--navy);font-size:13px;line-height:1.5;}}

/* ── TOP HEADER ── */
.top-header{{background:var(--w);border-bottom:1px solid var(--border);padding:0 28px;height:48px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:200;}}
.th-logo{{display:flex;align-items:center;gap:10px;}}
.th-nrc{{width:32px;height:32px;background:var(--navy);border-radius:4px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:11px;color:#fff;letter-spacing:.5px;}}
.th-title{{font-size:15px;font-weight:600;color:var(--navy);}}
.th-date{{font-size:12px;color:var(--g4);}}
.th-markets{{margin-left:auto;font-size:11px;color:var(--g4);}}
.th-markets span{{margin-left:8px;}}



/* ── LAYOUT ── */
.page{{max-width:1100px;margin:0 auto;padding:20px 24px;}}
.two-col{{display:grid;grid-template-columns:1fr 340px;gap:20px;align-items:start;}}

/* ── STAT CARDS ── */
.stat-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;}}
.stat-card{{background:var(--w);border:1px solid var(--border);border-radius:6px;padding:14px 16px;}}
.stat-label{{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:1.2px;color:var(--g4);margin-bottom:6px;font-family:'DM Mono',monospace;}}
.stat-value{{font-size:26px;font-weight:700;color:var(--navy);line-height:1;margin-bottom:4px;}}
.stat-note{{font-size:11px;}}

/* ── SECTION HEADERS ── */
.sec-header{{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:var(--g4);margin-bottom:10px;font-family:'DM Mono',monospace;padding-bottom:6px;border-bottom:1px solid var(--border);}}

/* ── HEADLINE LIST ── */
.hl-panel{{background:var(--w);border:1px solid var(--border);border-radius:6px;overflow:hidden;}}
.hl-row{{display:flex;align-items:center;gap:12px;padding:11px 16px;border-bottom:1px solid var(--g1);text-decoration:none;color:inherit;transition:background .12s;}}
.hl-row:last-child{{border-bottom:none;}}
.hl-row:hover{{background:var(--off2);}}
.hl-left{{display:flex;align-items:flex-start;gap:10px;flex:1;min-width:0;}}
.hl-text{{flex:1;min-width:0;}}
.hl-title{{font-size:13px;font-weight:500;color:var(--navy);line-height:1.35;margin-bottom:2px;}}
.hl-sub{{font-size:11px;color:var(--g4);}}
.hl-right{{flex-shrink:0;}}
.data-point{{display:inline-block;font-family:'DM Mono',monospace;font-size:11px;font-weight:600;color:var(--bluel);background:#eef3fb;padding:1px 6px;border-radius:3px;margin-left:6px;vertical-align:middle;}}
.sent-dot{{width:8px;height:8px;border-radius:50%;display:inline-block;}}

/* BADGES */
.mbadge{{display:inline-block;font-size:9px;font-weight:600;color:#fff;padding:2px 7px;border-radius:3px;white-space:nowrap;text-transform:uppercase;letter-spacing:.5px;flex-shrink:0;margin-top:2px;}}
.abadge{{display:inline-block;font-size:9px;color:#fff;padding:1px 6px;border-radius:3px;}}
.sent-pill{{font-size:9px;padding:2px 8px;border-radius:10px;font-family:'DM Mono',monospace;font-weight:600;}}

/* ── RIGHT PANEL ── */
.right-col{{display:flex;flex-direction:column;gap:16px;}}

.signal-panel{{background:var(--w);border:1px solid var(--border);border-radius:6px;padding:16px;}}
.signal-card{{display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--g1);}}
.signal-card:last-child{{border-bottom:none;padding-bottom:0;}}
.signal-card:first-child{{padding-top:0;}}
.signal-icon{{width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#fff;flex-shrink:0;margin-top:1px;}}
.signal-summary{{font-size:12px;color:var(--g6);line-height:1.5;margin-bottom:2px;}}
.signal-source{{font-size:10px;color:var(--g3);font-family:'DM Mono',monospace;}}

/* VACANCY WATCH */
.vacancy-panel{{background:var(--w);border:1px solid var(--border);border-radius:6px;padding:16px;}}
.vac-row{{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--g1);}}
.vac-row:last-child{{border-bottom:none;}}
.vac-label{{font-size:12px;color:var(--g6);}}
.vac-val{{font-size:12px;font-weight:600;color:var(--navy);font-family:'DM Mono',monospace;}}
.vac-bar{{width:80px;height:4px;background:var(--g1);border-radius:2px;margin:0 10px;overflow:hidden;}}
.vac-fill{{height:100%;border-radius:2px;}}

/* ── TRANSACTIONS ── */
.tx-panel{{background:var(--w);border:1px solid var(--border);border-radius:6px;padding:16px 16px 4px;margin-top:20px;}}
.tx-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border);border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-top:0;}}
.tx-cell{{background:var(--w);padding:12px 14px;}}
.tx-addr{{font-size:12px;font-weight:600;color:var(--navy);margin-bottom:3px;}}
.tx-detail{{font-size:13px;font-weight:700;color:var(--bluel);font-family:'DM Mono',monospace;margin-bottom:2px;}}
.tx-who{{font-size:11px;color:var(--g4);}}

/* ── TABS ── */
.tab-bar{{display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:20px;}}
.tab-btn{{background:none;border:none;padding:8px 18px;font-size:13px;font-weight:500;color:var(--g4);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;font-family:var(--font);transition:all .15s;}}
.tab-btn.on{{color:var(--navy);border-bottom-color:var(--navy);}}
.tab-pane{{display:none;}}.tab-pane.on{{display:block;}}

/* ── ARCHIVE ── */
.arc-wrap{{background:var(--w);border:1px solid var(--border);border-radius:6px;overflow:auto;}}
.arc-table{{width:100%;border-collapse:collapse;font-size:12px;}}
.arc-table th{{text-align:left;padding:9px 14px;font-size:9px;font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:1.5px;color:var(--g4);border-bottom:2px solid var(--g1);background:var(--off);white-space:nowrap;}}
.arc-table td{{padding:10px 14px;border-bottom:1px solid var(--g1);vertical-align:top;}}
.arc-table tr:last-child td{{border-bottom:none;}}.arc-table tr:hover td{{background:var(--off2);}}
.arc-link{{color:var(--navy);font-weight:500;text-decoration:none;}}.arc-link:hover{{color:var(--bluel);text-decoration:underline;}}
.td-date{{font-family:'DM Mono',monospace;font-size:11px;color:var(--g4);white-space:nowrap;}}
.td-sum{{font-size:11px;color:var(--g4);line-height:1.5;max-width:360px;}}
.frow{{display:flex;align-items:center;gap:8px;margin-bottom:14px;}}
.fsearch{{border:1px solid var(--border);border-radius:4px;padding:5px 12px;font-size:12px;font-family:var(--font);outline:none;width:200px;margin-left:auto;}}
.fsearch:focus{{border-color:var(--bluel);}}

/* TOAST */
.toast{{position:fixed;bottom:20px;right:20px;z-index:999;background:var(--navy);color:#fff;border-radius:4px;padding:10px 16px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,0.2);opacity:0;transform:translateY(6px);transition:all .2s;pointer-events:none;border-left:3px solid #4a8fd4;max-width:300px;line-height:1.5;}}
.toast.show{{opacity:1;transform:translateY(0);}}

.empty{{text-align:center;padding:48px;color:var(--g4);font-size:12px;font-family:'DM Mono',monospace;}}

@media(max-width:900px){{
  .two-col{{grid-template-columns:1fr;}}
  .right-col{{display:none;}}
  .stat-row{{grid-template-columns:repeat(2,1fr);}}
  .tx-grid{{grid-template-columns:repeat(2,1fr);}}
  .page{{padding:12px 14px;}}
  .top-header{{padding:0 14px;}}
  .th-markets{{display:none;}}
}}
</style>
</head>
<body>

<header class="top-header">
  <div class="th-logo">
    <div class="th-nrc">NRC</div>
    <div>
      <div class="th-title">Market Intelligence Dashboard</div>
      <div class="th-date">{fdate}</div>
    </div>
  </div>
  <div class="th-markets">
    <span>Boston</span><span>·</span><span>New York</span><span>·</span>
    <span>Maine</span><span>·</span><span>Pittsburgh</span><span>·</span><span>California</span>
  </div>
  <div style="display:flex;gap:8px;align-items:center;margin-left:16px;">
    <div class="tab-bar" style="border:none;margin:0;gap:4px;">
      <button class="tab-btn on" onclick="switchTab('today',this)" style="padding:4px 12px;font-size:12px;">Today</button>
      <button class="tab-btn" onclick="switchTab('archive',this)" style="padding:4px 12px;font-size:12px;">Archive</button>
    </div>

  </div>
</header>

<div class="page">

  <div class="tab-pane on" id="tab-today">

    <!-- STAT CARDS -->
    <div class="stat-row">
      {stat_cards if stat_cards else f'''
      <div class="stat-card"><div class="stat-label">Articles Today</div><div class="stat-value">{len(today_only)}</div><div class="stat-note" style="color:var(--g4)">Ranked by relevance</div></div>
      <div class="stat-card"><div class="stat-label">Bullish Signals</div><div class="stat-value" style="color:var(--greenl)">{sum(1 for a in today_only if a.get('sentiment')=='bullish')}</div><div class="stat-note" style="color:var(--greenl)">↑ Positive outlook</div></div>
      <div class="stat-card"><div class="stat-label">Bearish Signals</div><div class="stat-value" style="color:var(--redl)">{sum(1 for a in today_only if a.get('sentiment')=='bearish')}</div><div class="stat-note" style="color:var(--redl)">↓ Watch closely</div></div>
      <div class="stat-card"><div class="stat-label">Archive Total</div><div class="stat-value">{len(archive)}</div><div class="stat-note" style="color:var(--g4)">All time</div></div>'''}
    </div>

    <div class="two-col">

      <!-- LEFT: HEADLINES -->
      <div>
        <div class="sec-header">Top Headlines — All Markets</div>
        <div class="hl-panel">
          {headline_rows if headline_rows else '<div class="empty">No articles yet — run the scraper.</div>'}
        </div>

        <!-- TRANSACTIONS -->
        {f'''<div class="tx-panel" style="margin-top:20px;">
          <div class="sec-header">Notable Transactions — Recent Closes &amp; Filings</div>
          <div class="tx-grid">{tx_cells}</div>
        </div>''' if tx_cells else ""}
      </div>

      <!-- RIGHT: SIGNALS + VACANCY -->
      <div class="right-col">
        <div class="signal-panel">
          <div class="sec-header">Market Signals</div>
          {signal_cards}
        </div>

        <div class="vacancy-panel">
          <div class="sec-header">Vacancy Watch — Boston Sub-Markets</div>
          <div class="vac-row"><span class="vac-label">Industrial (Greater Boston)</span><div class="vac-bar"><div class="vac-fill" style="width:25%;background:var(--greenl)"></div></div><span class="vac-val">{next((s['value'] for s in snapshot if 'industrial' in s.get('label','').lower()),bullish > 0 and '~5%' or '—')}</span></div>
          <div class="vac-row"><span class="vac-label">Office (Metro Boston)</span><div class="vac-bar"><div class="vac-fill" style="width:85%;background:var(--redl)"></div></div><span class="vac-val">{next((s['value'] for s in snapshot if 'office' in s.get('label','').lower()),'~18%')}</span></div>
          <div class="vac-row"><span class="vac-label">Lab / Life Science</span><div class="vac-bar"><div class="vac-fill" style="width:55%;background:#b8924a)"></div></div><span class="vac-val">Recovering</span></div>
          <div class="vac-row"><span class="vac-label">Multifamily (Metro)</span><div class="vac-bar"><div class="vac-fill" style="width:20%;background:var(--greenl)"></div></div><span class="vac-val">Tight</span></div>
        </div>
      </div>

    </div>
  </div>

  <!-- ARCHIVE TAB -->
  <div class="tab-pane" id="tab-archive">
    <div class="frow">
      <span style="font-size:11px;color:var(--g4);font-family:'DM Mono',monospace">{len(archive)} ARTICLES IN ARCHIVE</span>
      <input class="fsearch" placeholder="Search archive…" id="search-arc" oninput="filterArc()">
    </div>
    <div class="arc-wrap">
      <table class="arc-table">
        <thead><tr><th>Date</th><th>Market</th><th>Headline</th><th>Summary</th><th>Sentiment</th></tr></thead>
        <tbody id="arc-tbody">{arc_rows}</tbody>
      </table>
    </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
function switchTab(n,btn){{
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('on'));
  document.getElementById('tab-'+n).classList.add('on');
  btn.classList.add('on');
}}
function filterArc(){{
  const q=document.getElementById('search-arc').value.toLowerCase();
  document.querySelectorAll('#arc-tbody tr').forEach(r=>{{r.style.display=!q||r.innerText.toLowerCase().includes(q)?'':'none';}});
}}
function toast(msg,ms=4500){{
  const el=document.getElementById('toast');
  el.innerHTML=msg;el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'),ms);
}}

</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main():
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n{'='*55}\nNRC Scraper — {today_str}\n{'='*55}\n")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    news_api_key = os.environ["NEWS_API_KEY"]

    # 1. Fetch headlines via NewsAPI (works from GitHub Actions)
    print("Fetching headlines via NewsAPI...")
    all_headlines = fetch_headlines_newsapi(news_api_key)

    # 2. Single Claude call — rank, summarize, extract data
    print("\nRanking with Claude…")
    articles, snapshot, transactions = rank_with_claude(client, all_headlines)

    # 3. Add metadata
    enriched = []
    for a in articles:
        enriched.append({**a, "date": today_str, "id": hashlib.md5(a["url"].encode()).hexdigest()[:10]})

    # 4. Archive — keep only last 3 days of articles
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    archive = load_archive()
    archive = [a for a in archive if a.get("date","") >= cutoff]
    existing = {a["url"] for a in archive}
    new_arts = [a for a in enriched if a["url"] not in existing]
    full_archive = new_arts + archive
    save_archive(full_archive)
    print(f"  {len(new_arts)} new → {len(full_archive)} total in archive (last 30 days)")

    # 5. Generate dashboard
    print("\nGenerating dashboard…")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(generate_html(enriched, full_archive, today_str, snapshot, transactions))

    print(f"\n{'='*55}\nDone → docs/index.html\n{'='*55}\n")

if __name__ == "__main__":
    main()
