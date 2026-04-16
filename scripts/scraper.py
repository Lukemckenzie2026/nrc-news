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
from bs4 import BeautifulSoup
import anthropic

# ─────────────────────────────────────────────────────────────────
# SOURCES — add/remove freely
# ─────────────────────────────────────────────────────────────────
SOURCES = [
    {"name": "Bisnow Boston",           "url": "https://www.bisnow.com",        "section_url": "https://www.bisnow.com/boston"},
    {"name": "CoStar News",             "url": "https://www.costar.com",        "section_url": "https://www.costar.com/news"},
    {"name": "The Real Deal",           "url": "https://therealdeal.com",       "section_url": "https://therealdeal.com/boston/"},
    {"name": "GlobeSt",                 "url": "https://www.globest.com",       "section_url": "https://www.globest.com/"},
    {"name": "Commercial Observer",     "url": "https://commercialobserver.com","section_url": "https://commercialobserver.com/"},
    {"name": "Wall Street Journal",     "url": "https://www.wsj.com",           "section_url": "https://www.wsj.com/real-estate"},
    {"name": "Boston Business Journal", "url": "https://www.bizjournals.com",   "section_url": "https://www.bizjournals.com/boston/real_estate"},
    {"name": "Crain's New York",        "url": "https://www.crainsnewyork.com", "section_url": "https://www.crainsnewyork.com/real-estate"},
    {"name": "SF Business Times",       "url": "https://www.bizjournals.com",   "section_url": "https://www.bizjournals.com/sanfrancisco/real_estate"},
    {"name": "Boston Globe",            "url": "https://www.bostonglobe.com",   "section_url": "https://www.bostonglobe.com/business/real-estate/"},
    {"name": "New York Times",          "url": "https://www.nytimes.com",       "section_url": "https://www.nytimes.com/section/realestate"},
]

# ─────────────────────────────────────────────────────────────────
# PROMPT — edit freely
# ─────────────────────────────────────────────────────────────────
RANKING_PROMPT = """
You are a senior research analyst at North River Company (NRC), a real estate private equity firm based in Boston.

NRC's focus:
- Markets: Boston, New York, Maine, Pittsburgh, California
- Asset classes: industrial, life science, Class B office, cold storage, tower residential (100+ units)
- Strategy: acquisitions, asset management, value-add, opportunistic, core/core-plus
- Also interested in: cap rates, interest rates, CMBS, private credit, CRE market trends, major lease signings, distressed assets

You will receive a list of article headlines scraped from CRE news sources today.

Your job:
1. Pick the 10 most relevant and useful articles for NRC's team
2. For each, write a 2-sentence summary of what the article is likely about and why it matters to NRC
3. Assign a sentiment: bullish, bearish, or neutral (from NRC's perspective)

Return a JSON array of exactly 10 items (fewer if less than 10 are relevant), ordered from most to least relevant:
[
  {
    "title": "exact headline as given",
    "url": "exact url as given",
    "source": "exact source as given",
    "summary": "2-sentence summary of what this means for NRC",
    "sentiment": "bullish | bearish | neutral"
  }
]

Return ONLY valid JSON. No markdown, no commentary.
"""

HEADERS      = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
ROOT         = Path(__file__).parent.parent
OUTPUT_FILE  = ROOT / "docs" / "index.html"
ARCHIVE_FILE = ROOT / "docs" / "data" / "archive.json"


# ─────────────────────────────────────────────────────────────────
# SCRAPING
# ─────────────────────────────────────────────────────────────────
def scrape_headlines(source):
    try:
        r = requests.get(source["section_url"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        results, seen = [], set()
        for tag in soup.find_all("a", href=True):
            text = tag.get_text(strip=True)
            href = tag["href"]
            if (30 < len(text) < 200
                    and not any(s in href for s in ["#","javascript","mailto","login","subscribe","account","signup"])
                    and text not in seen):
                if href.startswith("/"): href = source["url"] + href
                elif not href.startswith("http"): continue
                seen.add(text)
                results.append({"title": text, "url": href, "source": source["name"]})
        count = min(len(results), 30)
        print(f"  [{source['name']}] {count} headlines")
        return results[:30]
    except Exception as e:
        print(f"  [{source['name']}] Error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────
# CLAUDE — one call, returns top 10 with summaries
# ─────────────────────────────────────────────────────────────────
def rank_with_claude(client, all_headlines):
    # Just send titles, urls, sources — no body text needed
    headline_list = [{"title": a["title"], "url": a["url"], "source": a["source"]} for a in all_headlines]

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": f"{RANKING_PROMPT}\n\nHeadlines:\n{json.dumps(headline_list, indent=2)}"
        }]
    )

    raw = re.sub(r"^```json|^```|```$", "", msg.content[0].text.strip(), flags=re.MULTILINE).strip()
    results = json.loads(raw)
    print(f"  Claude returned {len(results)} articles")
    return results


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


def generate_html(today, archive, run_date):
    fdate   = datetime.strptime(run_date,"%Y-%m-%d").strftime("%B %d, %Y")
    bullish = sum(1 for a in today if a.get("sentiment")=="bullish")
    bearish = sum(1 for a in today if a.get("sentiment")=="bearish")
    neutral = sum(1 for a in today if a.get("sentiment")=="neutral")

    cards_html = "".join(article_card(a, i+1, True) for i,a in enumerate(today)) if today else '<div class="empty">No articles yet — run the scraper to populate.</div>'
    arc_html   = archive_rows_html(archive)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NRC Market Intelligence — {fdate}</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{
  --navy:#0d1c2e;--navy2:#152540;--navy3:#1d3560;
  --blue:#2660a4;--bluel:#4a8fd4;--bluep:#deeaf8;
  --gold:#b8924a;--goldp:#f7edd9;
  --w:#fff;--off:#f5f7fa;
  --g1:#eaecf2;--g2:#ced4e0;--g4:#8492a8;--g6:#4a5668;
  --green:#1e6e4a;--red:#b53325;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'DM Sans',sans-serif;background:var(--off);color:var(--navy);font-size:14px;line-height:1.6;}}

/* TOPBAR */
.topbar{{background:var(--navy);position:sticky;top:0;z-index:300;box-shadow:0 2px 12px rgba(0,0,0,0.2);}}
.topbar-inner{{max-width:860px;margin:0 auto;padding:0 24px;height:52px;display:flex;align-items:center;gap:16px;}}
.tb-name{{font-family:'Cormorant Garamond',serif;font-size:16px;font-weight:600;color:#fff;letter-spacing:.3px;}}
.tb-sub{{font-family:'DM Mono',monospace;font-size:8px;color:var(--bluel);text-transform:uppercase;letter-spacing:2px;margin-top:1px;}}
.tb-date{{font-family:'DM Mono',monospace;font-size:11px;color:rgba(255,255,255,0.3);border-left:1px solid rgba(255,255,255,0.1);padding-left:16px;}}
.tb-right{{display:flex;align-items:center;gap:8px;margin-left:auto;}}
.tb-nav button{{background:transparent;border:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.6);border-radius:4px;padding:5px 14px;font-size:12px;font-family:'DM Sans',sans-serif;cursor:pointer;transition:all .15s;}}
.tb-nav button:hover,.tb-nav button.on{{background:rgba(255,255,255,0.1);color:#fff;border-color:rgba(255,255,255,0.3);}}
.rerun-btn{{background:var(--gold);color:var(--navy);border:none;border-radius:4px;padding:5px 16px;font-size:12px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;transition:opacity .15s;}}
.rerun-btn:hover{{opacity:.85;}}.rerun-btn:disabled{{opacity:.5;cursor:wait;}}

/* PROGRESS */
.prog-wrap{{height:2px;background:rgba(255,255,255,0.06);overflow:hidden;display:none;}}
.prog-wrap.show{{display:block;}}
.prog-fill{{height:100%;width:0%;background:var(--gold);transition:width .5s ease;}}

/* TOAST */
.toast{{position:fixed;bottom:24px;right:24px;z-index:9999;background:var(--navy);color:#fff;border-radius:6px;padding:12px 20px;font-size:13px;box-shadow:0 4px 20px rgba(0,0,0,0.25);opacity:0;transform:translateY(8px);transition:all .25s;pointer-events:none;border-left:3px solid var(--gold);max-width:340px;line-height:1.5;}}
.toast.show{{opacity:1;transform:translateY(0);}}

/* HERO */
.hero{{background:linear-gradient(135deg,var(--navy2) 0%,var(--navy3) 100%);padding:32px 24px 28px;}}
.hero-inner{{max-width:860px;margin:0 auto;}}
.hero-eyebrow{{font-family:'DM Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:2px;color:var(--bluel);margin-bottom:8px;}}
.hero-title{{font-family:'Cormorant Garamond',serif;font-size:36px;font-weight:700;color:#fff;line-height:1.1;letter-spacing:-.3px;margin-bottom:20px;}}
.hero-title em{{color:var(--gold);font-style:normal;}}
.hero-stats{{display:flex;gap:24px;}}
.hstat{{display:flex;align-items:center;gap:8px;}}
.hstat-val{{font-family:'Cormorant Garamond',serif;font-size:28px;color:#fff;line-height:1;}}
.hstat-lbl{{font-size:11px;color:rgba(255,255,255,0.4);line-height:1.3;}}

/* LAYOUT */
.wrap{{max-width:860px;margin:0 auto;padding:28px 24px;}}
.tab-pane{{display:none;}}.tab-pane.on{{display:block;}}

/* FILTER ROW */
.frow{{display:flex;align-items:center;gap:8px;margin-bottom:20px;flex-wrap:wrap;}}
.flabel{{font-size:10px;font-family:'DM Mono',monospace;color:var(--g4);text-transform:uppercase;letter-spacing:1.5px;}}
.fchip{{border:1px solid var(--g2);background:var(--w);border-radius:20px;padding:4px 14px;font-size:12px;cursor:pointer;color:var(--g6);transition:all .15s;user-select:none;}}
.fchip:hover{{border-color:var(--blue);color:var(--blue);}}.fchip.on{{background:var(--navy);border-color:var(--navy);color:#fff;}}
.fsearch{{border:1px solid var(--g2);border-radius:20px;padding:5px 16px;font-size:12px;font-family:'DM Sans',sans-serif;outline:none;width:190px;margin-left:auto;transition:border-color .2s;background:var(--w);}}
.fsearch:focus{{border-color:var(--blue);}}

/* ARTICLE CARDS */
.cards{{display:flex;flex-direction:column;gap:2px;}}

.acard{{
  display:flex;align-items:flex-start;gap:0;
  background:var(--w);border:1px solid var(--g2);border-radius:6px;
  text-decoration:none;color:inherit;
  transition:all .18s;
  animation:fu .2s ease both;
  overflow:hidden;
}}
.acard:hover{{border-color:var(--bluel);box-shadow:0 2px 16px rgba(13,28,46,0.09);transform:translateX(2px);}}
@keyframes fu{{from{{opacity:0;transform:translateY(5px)}}to{{opacity:1;transform:translateY(0)}}}}

.acard-rank{{
  width:48px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-family:'Cormorant Garamond',serif;font-size:22px;font-weight:700;
  color:var(--g2);
  background:var(--off);
  border-right:1px solid var(--g1);
  align-self:stretch;
}}

.acard-content{{flex:1;padding:14px 18px;min-width:0;}}

.acard-meta{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;}}
.acard-source{{font-family:'DM Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--blue);font-weight:500;}}
.badge-today{{font-size:9px;background:rgba(30,110,74,0.1);color:var(--green);padding:2px 7px;border-radius:10px;font-family:'DM Mono',monospace;letter-spacing:1px;}}
.badge-date{{font-size:9px;background:var(--g1);color:var(--g4);padding:2px 7px;border-radius:10px;font-family:'DM Mono',monospace;}}
.sent-pill{{font-size:9px;padding:2px 8px;border-radius:10px;font-family:'DM Mono',monospace;letter-spacing:.5px;font-weight:600;}}

.acard-title{{
  font-family:'Cormorant Garamond',serif;
  font-size:20px;font-weight:700;
  color:var(--navy);line-height:1.25;
  margin-bottom:7px;
}}

.acard-summary{{
  font-size:13px;color:var(--g6);
  line-height:1.6;
}}

.acard-arrow{{
  padding:0 16px;display:flex;align-items:center;
  font-size:18px;color:var(--g2);flex-shrink:0;
  transition:all .15s;align-self:stretch;
}}
.acard:hover .acard-arrow{{color:var(--blue);transform:translateX(3px);}}

/* ARCHIVE */
.arc-wrap{{background:var(--w);border:1px solid var(--g2);border-radius:6px;overflow:auto;}}
.arc-table{{width:100%;border-collapse:collapse;font-size:13px;}}
.arc-table th{{text-align:left;padding:10px 14px;font-size:9px;font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:1.5px;color:var(--g4);border-bottom:2px solid var(--g1);background:var(--off);white-space:nowrap;}}
.arc-table td{{padding:11px 14px;border-bottom:1px solid var(--g1);vertical-align:top;}}
.arc-table tr:last-child td{{border-bottom:none;}}
.arc-table tr:hover td{{background:#f0f5fd;}}
.arc-link{{color:var(--navy);font-weight:600;text-decoration:none;font-family:'Cormorant Garamond',serif;font-size:15px;line-height:1.3;}}.arc-link:hover{{color:var(--blue);}}
.td-mono{{font-family:'DM Mono',monospace;font-size:11px;color:var(--g4);white-space:nowrap;}}
.td-src{{font-family:'DM Mono',monospace;font-size:10px;color:var(--blue);white-space:nowrap;}}
.td-sum{{font-size:12px;color:var(--g6);line-height:1.5;max-width:400px;}}

.empty{{text-align:center;padding:60px;color:var(--g4);font-family:'DM Mono',monospace;font-size:12px;}}

@media(max-width:600px){{
  .wrap{{padding:16px;}}
  .topbar-inner{{padding:0 16px;}}
  .hero{{padding:24px 16px 20px;}}
  .hero-title{{font-size:28px;}}
  .acard-rank{{width:36px;font-size:18px;}}
  .acard-title{{font-size:17px;}}
  .hero-stats{{gap:16px;}}
}}
</style>
</head>
<body>

<header class="topbar">
  <div class="prog-wrap" id="prog"><div class="prog-fill" id="prog-fill"></div></div>
  <div class="topbar-inner">
    <div>
      <div class="tb-name">North River Company</div>
      <div class="tb-sub">Market Intelligence</div>
    </div>
    <div class="tb-date">{fdate}</div>
    <div class="tb-right">
      <div class="tb-nav">
        <button class="on" onclick="switchTab('today',this)">Today</button>
        <button onclick="switchTab('archive',this)">Archive</button>
      </div>
      <button class="rerun-btn" id="rerun-btn" onclick="rerun()">↻ Rerun</button>
    </div>
  </div>
</header>

<div class="hero">
  <div class="hero-inner">
    <div class="hero-eyebrow">Daily Brief · {fdate}</div>
    <div class="hero-title">Market <em>Intelligence</em></div>
    <div class="hero-stats">
      <div class="hstat">
        <div class="hstat-val">{len(today)}</div>
        <div class="hstat-lbl">Top<br>Articles</div>
      </div>
      <div class="hstat" style="opacity:.4;width:1px;background:rgba(255,255,255,0.2);margin:4px 0;"></div>
      <div class="hstat">
        <div class="hstat-val" style="color:#5ecf9e">{bullish}</div>
        <div class="hstat-lbl">Bullish<br>Signal</div>
      </div>
      <div class="hstat">
        <div class="hstat-val" style="color:#e07060">{bearish}</div>
        <div class="hstat-lbl">Bearish<br>Signal</div>
      </div>
      <div class="hstat">
        <div class="hstat-val" style="color:#7aadda">{neutral}</div>
        <div class="hstat-lbl">Neutral<br>Signal</div>
      </div>
      <div class="hstat" style="opacity:.4;width:1px;background:rgba(255,255,255,0.2);margin:4px 0;"></div>
      <div class="hstat">
        <div class="hstat-val">{len(archive)}</div>
        <div class="hstat-lbl">Archive<br>Total</div>
      </div>
    </div>
  </div>
</div>

<div class="wrap">

  <div class="tab-pane on" id="tab-today">
    <div class="frow">
      <span class="flabel">Show:</span>
      <div class="fchip on" onclick="filterSent('all',this)">All</div>
      <div class="fchip" onclick="filterSent('bullish',this)">● Bullish</div>
      <div class="fchip" onclick="filterSent('bearish',this)">● Bearish</div>
      <div class="fchip" onclick="filterSent('neutral',this)">● Neutral</div>
      <input class="fsearch" placeholder="Search…" id="search-today" oninput="applyFilters()">
    </div>
    <div class="cards" id="cards-today">{cards_html}</div>
  </div>

  <div class="tab-pane" id="tab-archive">
    <div class="frow" style="margin-bottom:16px">
      <span class="flabel">Archive — {len(archive)} articles</span>
      <input class="fsearch" style="margin-left:auto" placeholder="Search…" id="search-arc" oninput="filterArc()">
    </div>
    <div class="arc-wrap">
      <table class="arc-table">
        <thead><tr>
          <th>Date</th><th>Source</th><th>Headline</th><th>Summary</th><th>Sentiment</th>
        </tr></thead>
        <tbody id="arc-tbody">{arc_html}</tbody>
      </table>
    </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
function switchTab(n,btn){{
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.tb-nav button').forEach(b=>b.classList.remove('on'));
  document.getElementById('tab-'+n).classList.add('on');
  btn.classList.add('on');
}}

let activeSent='all';
function filterSent(s,el){{
  activeSent=s;
  document.querySelectorAll('.fchip').forEach(c=>c.classList.remove('on'));
  el.classList.add('on');
  applyFilters();
}}
function applyFilters(){{
  const q=document.getElementById('search-today').value.toLowerCase();
  document.querySelectorAll('#cards-today .acard').forEach(c=>{{
    const ok=(activeSent==='all'||c.dataset.sentiment===activeSent)&&(!q||c.innerText.toLowerCase().includes(q));
    c.style.display=ok?'':'none';
  }});
}}
function filterArc(){{
  const q=document.getElementById('search-arc').value.toLowerCase();
  document.querySelectorAll('#arc-tbody tr').forEach(r=>{{
    r.style.display=!q||r.innerText.toLowerCase().includes(q)?'':'none';
  }});
}}

function toast(msg,ms=4500){{
  const el=document.getElementById('toast');
  el.innerHTML=msg;el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'),ms);
}}

async function rerun(){{
  const GITHUB_USER='Lukemckenzie2026';
  const GITHUB_REPO='nrc-news';
  const TOKEN='{GITHUB_PAT}';
  if(!TOKEN||TOKEN===''||TOKEN==='{GITHUB_PAT}'){{
    toast('Rerun not configured yet — go to Actions tab on GitHub to run manually.',6000);
    return;
  }}
  const btn=document.getElementById('rerun-btn');
  const prog=document.getElementById('prog');
  const fill=document.getElementById('prog-fill');
  btn.disabled=true;btn.textContent='Triggering…';
  prog.classList.add('show');
  try{{
    const res=await fetch(
      `https://api.github.com/repos/${{GITHUB_USER}}/${{GITHUB_REPO}}/actions/workflows/daily.yml/dispatches`,
      {{method:'POST',headers:{{'Authorization':`Bearer ${{TOKEN}}`,'Accept':'application/vnd.github+json','Content-Type':'application/json'}},body:JSON.stringify({{ref:'main'}})}}
    );
    if(res.status===204){{
      let pct=5;
      const tick=setInterval(()=>{{pct=Math.min(pct+2,90);fill.style.width=pct+'%';}},3000);
      toast('✓ Running — takes ~2 min. Page reloads when done.',7000);
      await new Promise(r=>setTimeout(r,15000));
      for(let i=0;i<30;i++){{
        await new Promise(r=>setTimeout(r,8000));
        try{{
          const r2=await fetch(`https://api.github.com/repos/${{GITHUB_USER}}/${{GITHUB_REPO}}/actions/runs?per_page=1`,{{headers:{{'Authorization':`Bearer ${{TOKEN}}`,'Accept':'application/vnd.github+json'}}}});
          const d=await r2.json();
          const run=d.workflow_runs?.[0];
          if(run&&run.status==='completed'){{clearInterval(tick);fill.style.width='100%';toast('✓ Done — reloading…',2000);setTimeout(()=>location.reload(),2100);return;}}
        }}catch(_){{}}
      }}
      clearInterval(tick);
      toast('Still running — reload the page in a minute.',4000);
      btn.disabled=false;btn.textContent='↻ Rerun';prog.classList.remove('show');fill.style.width='0%';
    }}else{{
      toast(`⚠ GitHub error ${{res.status}} — check your PAT has workflow permissions.`,7000);
      btn.disabled=false;btn.textContent='↻ Rerun';prog.classList.remove('show');fill.style.width='0%';
    }}
  }}catch(e){{
    toast('⚠ Error: '+e.message,5000);
    btn.disabled=false;btn.textContent='↻ Rerun';prog.classList.remove('show');fill.style.width='0%';
  }}
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

    # 1. Scrape headlines from all sources
    all_headlines = []
    for source in SOURCES:
        print(f"Scraping: {source['name']}")
        all_headlines.extend(scrape_headlines(source))
        time.sleep(0.5)
    print(f"\nTotal headlines: {len(all_headlines)}")

    # 2. Single Claude call — rank and summarize top 10
    print("\nRanking with Claude…")
    top_articles = rank_with_claude(client, all_headlines)

    # 3. Add metadata
    enriched = []
    for a in top_articles:
        enriched.append({
            **a,
            "date": today_str,
            "id": hashlib.md5(a["url"].encode()).hexdigest()[:10]
        })

    # 4. Archive
    archive = load_archive()
    existing = {a["url"] for a in archive}
    new_arts = [a for a in enriched if a["url"] not in existing]
    full_archive = new_arts + archive
    save_archive(full_archive)
    print(f"  {len(new_arts)} new → {len(full_archive)} total in archive")

    # 5. Generate dashboard
    print("\nGenerating dashboard…")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(generate_html(enriched, full_archive, today_str))

    print(f"\n{'='*55}\nDone → docs/index.html\n{'='*55}\n")

if __name__ == "__main__":
    main()
