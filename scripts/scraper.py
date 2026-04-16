"""
NRC Market Intelligence Scraper
- Scrapes 11 CRE sources
- Fetches and stores FULL article text (not just headlines)
- Claude reads the full text to filter relevance and extract data
- Generates dashboard with inline article reader (no PDF)
"""

import json, os, re, time, hashlib, requests
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup
import anthropic

# ─────────────────────────────────────────────────────────────────
# SOURCES
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
# PROMPTS
# ─────────────────────────────────────────────────────────────────
RELEVANCE_PROMPT = """
You are a research analyst at North River Company (NRC), a real estate private equity firm in Boston.

NRC's focus:
- Markets: Boston, New York, Maine, Pittsburgh, California
- Asset classes: industrial, life science, Class B office, cold storage, tower residential (100+ units)
- Strategy: acquisitions, asset management, value-add, opportunistic, core/core-plus

You will be given a list of articles, each with a title AND the full article text.
Return ONLY the ones relevant to NRC as a JSON array.
Each item: { "title": string, "url": string, "source": string }
Return ONLY valid JSON. No markdown, no commentary.
"""

EXTRACTION_PROMPT = """
You are a real estate research analyst at North River Company (NRC).

Read the full article text below and:
1. Extract all market data present
2. Write a thorough summary based on the actual article content (not just the headline)

Return a JSON object with these exact keys (null if not mentioned):

{
  "summary": "3-4 sentence summary based on the full article content, including specific facts, figures, and quotes from the article",
  "relevance_reason": "One sentence: why this is specifically relevant to NRC",
  "market": "Market(s) covered e.g. Boston, Pittsburgh, National",
  "asset_class": "Asset class(es) e.g. Industrial, Life Science, Office",
  "vacancy_rate": "e.g. '12.4%' or null",
  "cap_rate": "e.g. '5.8%' or null",
  "asking_rent": "e.g. '$28 PSF NNN' or null",
  "transaction": "Deal size/price e.g. '$47M' or null",
  "absorption": "Net absorption e.g. '+120,000 SF' or null",
  "debt_terms": "Rate/loan terms e.g. 'SOFR + 285bps' or null",
  "pipeline": "Construction pipeline e.g. '2.1M SF' or null",
  "tenant": "Tenant name(s) or lease details or null",
  "sentiment": "bullish | bearish | neutral"
}

Return ONLY valid JSON. No markdown, no commentary.

Article title: {title}
Article text:
{text}
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
            if (30 < len(text) < 300
                    and not any(s in href for s in ["#","javascript","mailto","login","subscribe","account"])
                    and text not in seen):
                if href.startswith("/"): href = source["url"] + href
                elif not href.startswith("http"): continue
                seen.add(text)
                results.append({"title": text, "url": href, "source": source["name"]})
        print(f"  [{source['name']}] {min(len(results),40)} candidates")
        return results[:40]
    except Exception as e:
        print(f"  [{source['name']}] Error: {e}")
        return []


def fetch_article_text(url):
    """Fetch and clean the full article body text."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["nav","footer","aside","script","style","form","header","iframe",
                         ".ad","#ad",".advertisement",".subscribe-wall",".paywall"]): 
            tag.decompose()
        # Try common article body selectors in order of preference
        for sel in ["article", ".article-body", ".article__body", ".story-body",
                    ".post-content", ".entry-content", ".article-content",
                    "[itemprop='articleBody']", ".body-copy", "main"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                # Clean up excessive whitespace
                text = re.sub(r'\n{3,}', '\n\n', text)
                if len(text) > 200:  # make sure we got real content
                    return text
        # Fallback to full page
        text = soup.get_text(separator="\n", strip=True)
        return re.sub(r'\n{3,}', '\n\n', text)
    except Exception as e:
        return ""


# ─────────────────────────────────────────────────────────────────
# CLAUDE AI
# ─────────────────────────────────────────────────────────────────
def filter_with_claude(client, articles_with_text):
    """Filter using both headline AND article text for better accuracy."""
    # Build input with title + first 500 chars of text per article
    article_list = []
    for a in articles_with_text:
        preview = (a.get("body","") or "")[:500].replace("\n"," ").strip()
        article_list.append({
            "title": a["title"],
            "url": a["url"],
            "source": a["source"],
            "preview": preview
        })

    msg = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4000,
        messages=[{"role":"user","content":f"{RELEVANCE_PROMPT}\n\nArticles:\n{json.dumps(article_list,indent=2)}"}]
    )
    raw = re.sub(r"^```json|^```|```$","",msg.content[0].text.strip(),flags=re.MULTILINE).strip()
    filtered = json.loads(raw)
    print(f"\n  Claude selected {len(filtered)} relevant from {len(articles_with_text)}")
    return filtered


def extract_market_data(client, article):
    """Extract structured data from the full article text."""
    body = (article.get("body") or "").strip()
    if not body:
        return {k: None for k in ["summary","relevance_reason","market","asset_class",
                                   "vacancy_rate","cap_rate","asking_rent","transaction",
                                   "absorption","debt_terms","pipeline","tenant","sentiment"]}
    try:
        # Use up to 8000 chars of the article
        text_for_claude = body[:8000]
        prompt = EXTRACTION_PROMPT.replace("{title}", article["title"]).replace("{text}", text_for_claude)

        msg = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=1200,
            messages=[{"role":"user","content": prompt}]
        )
        raw = re.sub(r"^```json|^```|```$","",msg.content[0].text.strip(),flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"    Extraction error: {e}")
        return {}


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
def sb(s): return {"bullish":"rgba(30,110,74,0.08)","bearish":"rgba(181,51,37,0.08)","neutral":"rgba(38,96,164,0.08)"}.get(s or "neutral","rgba(38,96,164,0.08)")

def chip(label, val):
    if not val: return ""
    return f'<span class="dchip"><span class="dchip-k">{label}</span><span class="dchip-v">{val}</span></span>'

def escape_js_string(s):
    """Escape text for embedding in a JS string."""
    if not s: return ""
    return (s.replace("\\","\\\\")
             .replace("'","\\'")
             .replace("\n","\\n")
             .replace("\r","")
             .replace("</","<\\/"))

def escape_html(s):
    if not s: return ""
    return (s.replace("&","&amp;")
             .replace("<","&lt;")
             .replace(">","&gt;")
             .replace('"',"&quot;"))

def article_card(a, is_today=True):
    sent   = a.get("sentiment") or "neutral"
    art_id = a.get("id","x")
    body   = a.get("body","") or ""
    has_body = len(body.strip()) > 100

    chips = "".join([
        chip("Vacancy",   a.get("vacancy_rate")),
        chip("Cap Rate",  a.get("cap_rate")),
        chip("Rent",      a.get("asking_rent")),
        chip("Deal",      a.get("transaction")),
        chip("Absorption",a.get("absorption")),
        chip("Debt",      a.get("debt_terms")),
        chip("Pipeline",  a.get("pipeline")),
        chip("Tenant",    a.get("tenant")),
    ])
    has_data = any(a.get(k) for k in ["vacancy_rate","cap_rate","asking_rent","transaction",
                                       "absorption","debt_terms","pipeline","tenant"])

    date_badge = '<span class="badge-today">TODAY</span>' if is_today else f'<span class="badge-date">{a.get("date","")}</span>'

    read_btn = (f'<button class="btn-sm btn-read-full" onclick="openReader(\'{art_id}\')">Read Article</button>'
                if has_body else
                f'<a href="{a["url"]}" target="_blank" class="btn-sm btn-read-full">Read Article ↗</a>')

    # Embed body text as escaped JS for the reader modal
    body_escaped = escape_js_string(body[:12000])
    body_html_escaped = escape_html(body[:12000])

    return f"""<article class="acard" data-sentiment="{sent}" id="card-{art_id}">
  <div class="acard-body">
    <div class="acard-meta">
      <span class="acard-source">{a['source']}</span>
      {date_badge}
      <span class="sent-pill" style="color:{sc(sent)};background:{sb(sent)}">{sent.upper()}</span>
      <div class="acard-actions">
        <a href="{a['url']}" target="_blank" class="btn-sm btn-outline">Source ↗</a>
        {read_btn}
      </div>
    </div>
    <a class="acard-title" href="{a['url']}" target="_blank">{escape_html(a['title'])}</a>
    {f'<p class="acard-summary">{escape_html(a.get("summary",""))}</p>' if a.get("summary") else ""}
    {f'<p class="acard-relevance">{escape_html(a.get("relevance_reason",""))}</p>' if a.get("relevance_reason") else ""}
    {f'<div class="chips-row">{chips}</div>' if has_data else ""}
  </div>
  <div class="acard-tags">
    {'<span class="tag-market">'+escape_html(a.get("market",""))+'</span>' if a.get("market") else ""}
    {'<span class="tag-asset">'+escape_html(a.get("asset_class",""))+'</span>' if a.get("asset_class") else ""}
  </div>
  <div class="reader-data" id="reader-{art_id}" style="display:none"
       data-title="{escape_html(a['title'])}"
       data-source="{escape_html(a['source'])}"
       data-date="{a.get('date','')}"
       data-url="{a['url']}"
       data-body="{body_escaped}"
       data-summary="{escape_js_string(a.get('summary',''))}"
       data-relevance="{escape_js_string(a.get('relevance_reason',''))}">
  </div>
</article>"""


def snapshot_panel(articles):
    fields = [
        ("vacancy_rate","Vacancy"),("cap_rate","Cap Rate"),("asking_rent","Asking Rent"),
        ("transaction","Transaction"),("absorption","Absorption"),("debt_terms","Debt / Rate"),
        ("pipeline","Pipeline"),("tenant","Tenant / Lease"),
    ]
    rows = ""
    for key, label in fields:
        hits = [(a["title"],a[key],a["source"],a["url"]) for a in articles if a.get(key)]
        if not hits: continue
        items = "".join(
            f'<div class="snap-item"><a href="{u}" target="_blank" class="snap-hed">'
            f'{escape_html(t[:80])}{"…" if len(t)>80 else ""}</a>'
            f'<span class="snap-val">{escape_html(v)}</span>'
            f'<span class="snap-src">{s}</span></div>'
            for t,v,s,u in hits
        )
        rows += f'<div class="snap-row"><div class="snap-lbl">{label}</div><div class="snap-hits">{items}</div></div>'
    return rows or '<div class="snap-empty">No structured data extracted today.</div>'


def archive_rows_html(archive):
    return "".join(f"""<tr>
      <td class="td-mono">{a.get("date","")}</td>
      <td class="td-src">{escape_html(a["source"])}</td>
      <td><a href="{a['url']}" target="_blank" class="arc-link">{escape_html(a["title"])}</a></td>
      <td>{escape_html(a.get("market") or "—")}</td>
      <td>{escape_html(a.get("asset_class") or "—")}</td>
      <td class="td-num">{escape_html(a.get("vacancy_rate") or "—")}</td>
      <td class="td-num">{escape_html(a.get("cap_rate") or "—")}</td>
      <td class="td-num">{escape_html(a.get("asking_rent") or "—")}</td>
      <td class="td-num">{escape_html(a.get("transaction") or "—")}</td>
      <td><span class="sent-pill" style="color:{sc(a.get('sentiment'))};background:{sb(a.get('sentiment'))}">{(a.get("sentiment") or "—").upper()}</span></td>
    </tr>""" for a in archive)


def generate_html(today, archive, run_date):
    fdate    = datetime.strptime(run_date,"%Y-%m-%d").strftime("%B %d, %Y")
    bullish  = sum(1 for a in today if a.get("sentiment")=="bullish")
    bearish  = sum(1 for a in today if a.get("sentiment")=="bearish")
    data_pts = sum(1 for a in today for k in ["vacancy_rate","cap_rate","asking_rent",
               "transaction","absorption","debt_terms","pipeline","tenant"] if a.get(k))

    cards_html = "".join(article_card(a,True) for a in today) if today else '<div class="empty">No articles found. Run the scraper to populate.</div>'
    snap_html  = snapshot_panel(today)
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
  --r:6px;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
html{{scroll-behavior:smooth;}}
body{{font-family:'DM Sans',sans-serif;background:var(--off);color:var(--navy);font-size:14px;line-height:1.6;}}

/* TOPBAR */
.topbar{{background:var(--navy);position:sticky;top:0;z-index:300;}}
.topbar-inner{{max-width:1200px;margin:0 auto;padding:0 28px;height:52px;display:flex;align-items:center;gap:20px;}}
.tb-brand .tb-name{{font-family:'Cormorant Garamond',serif;font-size:15px;font-weight:600;color:#fff;letter-spacing:.3px;line-height:1;}}
.tb-brand .tb-sub{{font-family:'DM Mono',monospace;font-size:8px;color:var(--bluel);text-transform:uppercase;letter-spacing:2px;}}
.tb-date{{font-family:'DM Mono',monospace;font-size:11px;color:rgba(255,255,255,0.3);border-left:1px solid rgba(255,255,255,0.1);padding-left:18px;}}
.tb-right{{display:flex;align-items:center;gap:8px;margin-left:auto;}}
.tb-nav button{{background:transparent;border:1px solid rgba(255,255,255,0.12);color:rgba(255,255,255,0.55);border-radius:4px;padding:5px 14px;font-size:12px;font-family:'DM Sans',sans-serif;cursor:pointer;transition:all .15s;}}
.tb-nav button:hover,.tb-nav button.on{{background:rgba(255,255,255,0.1);color:#fff;border-color:rgba(255,255,255,0.25);}}
.rerun-btn{{background:var(--gold);color:var(--navy);border:none;border-radius:4px;padding:5px 16px;font-size:12px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;transition:opacity .15s;white-space:nowrap;}}
.rerun-btn:hover{{opacity:.88;}}.rerun-btn:disabled{{opacity:.5;cursor:wait;}}

/* PROGRESS */
.prog-wrap{{height:2px;background:rgba(255,255,255,0.06);overflow:hidden;display:none;}}
.prog-wrap.show{{display:block;}}
.prog-fill{{height:100%;width:0%;background:var(--gold);transition:width .5s ease;}}

/* TOAST */
.toast{{position:fixed;bottom:24px;right:24px;z-index:9999;background:var(--navy);color:#fff;border-radius:var(--r);padding:12px 20px;font-size:13px;box-shadow:0 4px 20px rgba(0,0,0,0.25);opacity:0;transform:translateY(8px);transition:all .25s;pointer-events:none;border-left:3px solid var(--gold);max-width:360px;line-height:1.5;}}
.toast.show{{opacity:1;transform:translateY(0);}}

/* HERO */
.hero{{background:linear-gradient(135deg,var(--navy2) 0%,var(--navy3) 100%);padding:28px 28px 24px;border-bottom:1px solid rgba(255,255,255,0.05);}}
.hero-inner{{max-width:1200px;margin:0 auto;display:flex;align-items:flex-end;gap:32px;}}
.hero-title{{font-family:'Cormorant Garamond',serif;font-size:34px;font-weight:600;color:#fff;line-height:1.1;letter-spacing:-.3px;}}
.hero-title em{{color:var(--gold);font-style:normal;}}
.hero-pills{{display:flex;gap:10px;margin-left:auto;flex-shrink:0;}}
.hpill{{text-align:center;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);border-radius:var(--r);padding:10px 18px;}}
.hpill-val{{font-family:'Cormorant Garamond',serif;font-size:26px;color:#fff;line-height:1;}}
.hpill-lbl{{font-size:9px;font-family:'DM Mono',monospace;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:1.5px;margin-top:2px;}}

/* LAYOUT */
.wrap{{max-width:1200px;margin:0 auto;padding:24px 28px;}}
.tab-pane{{display:none;}}.tab-pane.on{{display:block;}}

/* FILTERS */
.frow{{display:flex;align-items:center;gap:8px;margin-bottom:18px;flex-wrap:wrap;}}
.flabel{{font-size:10px;font-family:'DM Mono',monospace;color:var(--g4);text-transform:uppercase;letter-spacing:1.5px;}}
.fchip{{border:1px solid var(--g2);background:var(--w);border-radius:20px;padding:4px 13px;font-size:12px;cursor:pointer;color:var(--g6);transition:all .15s;}}
.fchip:hover{{border-color:var(--blue);color:var(--blue);}}.fchip.on{{background:var(--navy);border-color:var(--navy);color:#fff;}}
.fsearch{{border:1px solid var(--g2);border-radius:20px;padding:4px 14px;font-size:12px;font-family:'DM Sans',sans-serif;outline:none;width:200px;margin-left:auto;transition:border-color .2s;}}
.fsearch:focus{{border-color:var(--blue);}}

/* CARDS */
.cards{{display:flex;flex-direction:column;gap:10px;margin-bottom:32px;}}
.acard{{background:var(--w);border:1px solid var(--g2);border-radius:var(--r);transition:all .2s;animation:fu .25s ease both;overflow:hidden;}}
.acard:hover{{border-color:var(--bluel);box-shadow:0 2px 12px rgba(13,28,46,0.07);}}
@keyframes fu{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:translateY(0)}}}}

.acard-body{{padding:16px 20px;}}
.acard-meta{{display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;}}
.acard-source{{font-family:'DM Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--blue);font-weight:500;}}
.badge-today{{font-size:9px;background:rgba(30,110,74,0.1);color:var(--green);padding:2px 7px;border-radius:10px;font-family:'DM Mono',monospace;letter-spacing:1px;}}
.badge-date{{font-size:9px;background:var(--g1);color:var(--g4);padding:2px 7px;border-radius:10px;font-family:'DM Mono',monospace;}}
.sent-pill{{font-size:9px;padding:2px 8px;border-radius:10px;font-family:'DM Mono',monospace;letter-spacing:.5px;font-weight:500;}}
.acard-actions{{margin-left:auto;display:flex;gap:6px;align-items:center;}}

.btn-sm{{font-size:11px;padding:4px 11px;border-radius:4px;cursor:pointer;font-family:'DM Sans',sans-serif;transition:all .15s;text-decoration:none;display:inline-block;white-space:nowrap;border:1px solid transparent;font-weight:500;}}
.btn-outline{{border-color:var(--g2);color:var(--g6);background:transparent;}}.btn-outline:hover{{border-color:var(--blue);color:var(--blue);background:var(--bluep);}}
.btn-read-full{{border-color:var(--navy);color:var(--navy);background:transparent;}}.btn-read-full:hover{{background:var(--navy);color:#fff;}}

.acard-title{{display:block;font-family:'Cormorant Garamond',serif;font-size:19px;font-weight:600;color:var(--navy);text-decoration:none;line-height:1.3;margin-bottom:6px;transition:color .15s;}}
.acard-title:hover{{color:var(--blue);}}
.acard-summary{{font-size:13px;color:var(--g6);line-height:1.6;margin-bottom:4px;}}
.acard-relevance{{font-size:12px;color:var(--gold);border-left:2px solid var(--goldp);padding-left:9px;margin-top:6px;font-style:italic;}}

.chips-row{{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px;}}
.dchip{{display:inline-flex;border-radius:3px;overflow:hidden;border:1px solid var(--g2);}}
.dchip-k{{background:var(--navy);color:rgba(255,255,255,0.45);padding:2px 7px;font-family:'DM Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap;}}
.dchip-v{{background:var(--w);color:var(--navy);padding:2px 8px;font-weight:600;font-family:'DM Mono',monospace;font-size:11px;white-space:nowrap;}}

.acard-tags{{padding:8px 20px;border-top:1px solid var(--g1);display:flex;gap:6px;background:var(--off);}}
.tag-market{{font-size:10px;background:var(--bluep);color:var(--blue);padding:2px 8px;border-radius:3px;font-family:'DM Mono',monospace;}}
.tag-asset{{font-size:10px;background:var(--goldp);color:var(--gold);padding:2px 8px;border-radius:3px;font-family:'DM Mono',monospace;}}

/* SNAPSHOT */
.section-label{{font-family:'DM Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:2px;color:var(--g4);margin-bottom:12px;}}
.snapshot{{background:var(--w);border:1px solid var(--g2);border-radius:var(--r);overflow:hidden;}}
.snap-row{{display:flex;border-bottom:1px solid var(--g1);}}.snap-row:last-child{{border-bottom:none;}}
.snap-lbl{{width:120px;flex-shrink:0;padding:11px 14px;font-family:'DM Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:1px;color:var(--g4);background:var(--off);border-right:1px solid var(--g1);display:flex;align-items:flex-start;padding-top:13px;}}
.snap-hits{{flex:1;}}
.snap-item{{display:flex;align-items:center;gap:12px;padding:8px 14px;border-bottom:1px solid var(--g1);}}.snap-item:last-child{{border-bottom:none;}}
.snap-hed{{font-size:12px;color:var(--g6);text-decoration:none;flex:1;min-width:0;line-height:1.4;}}.snap-hed:hover{{color:var(--blue);}}
.snap-val{{font-family:'DM Mono',monospace;font-size:12px;font-weight:600;color:var(--navy);white-space:nowrap;background:var(--goldp);padding:2px 9px;border-radius:3px;border:1px solid rgba(184,146,74,0.2);}}
.snap-src{{font-size:10px;color:var(--g4);white-space:nowrap;font-family:'DM Mono',monospace;}}
.snap-empty{{padding:24px;text-align:center;color:var(--g4);font-size:12px;font-family:'DM Mono',monospace;}}

/* ARCHIVE */
.arc-wrap{{background:var(--w);border:1px solid var(--g2);border-radius:var(--r);overflow:auto;}}
.arc-table{{width:100%;border-collapse:collapse;font-size:13px;}}
.arc-table th{{text-align:left;padding:9px 14px;font-size:9px;font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:1.5px;color:var(--g4);border-bottom:2px solid var(--g1);background:var(--off);white-space:nowrap;}}
.arc-table td{{padding:10px 14px;border-bottom:1px solid var(--g1);vertical-align:middle;}}.arc-table tr:last-child td{{border-bottom:none;}}.arc-table tr:hover td{{background:#f0f5fd;}}
.arc-link{{color:var(--navy);font-weight:500;text-decoration:none;}}.arc-link:hover{{color:var(--blue);text-decoration:underline;}}
.td-mono{{font-family:'DM Mono',monospace;font-size:11px;color:var(--g4);white-space:nowrap;}}
.td-src{{font-family:'DM Mono',monospace;font-size:10px;color:var(--blue);white-space:nowrap;}}
.td-num{{font-family:'DM Mono',monospace;font-size:12px;font-weight:500;color:var(--navy);}}

.empty{{text-align:center;padding:48px;color:var(--g4);font-family:'DM Mono',monospace;font-size:13px;}}

/* READER MODAL */
.modal-overlay{{position:fixed;inset:0;background:rgba(13,28,46,0.7);z-index:500;display:none;align-items:flex-start;justify-content:center;padding:32px 16px;overflow-y:auto;backdrop-filter:blur(2px);}}
.modal-overlay.open{{display:flex;}}
.modal{{background:var(--w);border-radius:8px;width:100%;max-width:760px;margin:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);display:flex;flex-direction:column;max-height:90vh;}}
.modal-header{{padding:20px 24px 16px;border-bottom:1px solid var(--g1);display:flex;align-items:flex-start;gap:16px;flex-shrink:0;}}
.modal-header-text{{flex:1;min-width:0;}}
.modal-source{{font-family:'DM Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--blue);margin-bottom:6px;}}
.modal-title{{font-family:'Cormorant Garamond',serif;font-size:22px;font-weight:700;color:var(--navy);line-height:1.3;}}
.modal-close{{background:var(--off);border:1px solid var(--g2);border-radius:4px;width:32px;height:32px;cursor:pointer;font-size:16px;color:var(--g4);display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .15s;}}
.modal-close:hover{{background:var(--g1);color:var(--navy);}}
.modal-ai{{padding:16px 24px;background:var(--off);border-bottom:1px solid var(--g1);flex-shrink:0;}}
.modal-ai-label{{font-family:'DM Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:1.5px;color:var(--g4);margin-bottom:6px;}}
.modal-summary{{font-size:13px;color:var(--g6);line-height:1.6;margin-bottom:6px;}}
.modal-relevance{{font-size:12px;color:var(--gold);font-style:italic;border-left:2px solid var(--goldp);padding-left:8px;}}
.modal-body{{padding:24px;overflow-y:auto;flex:1;}}
.modal-body-text{{font-family:Georgia,serif;font-size:15px;line-height:1.8;color:#222;white-space:pre-wrap;word-break:break-word;}}
.modal-footer{{padding:14px 24px;border-top:1px solid var(--g1);display:flex;align-items:center;gap:10px;flex-shrink:0;background:var(--off);border-radius:0 0 8px 8px;}}
.modal-footer a{{font-size:12px;color:var(--blue);text-decoration:none;}}.modal-footer a:hover{{text-decoration:underline;}}
.modal-paywall-note{{font-size:12px;color:var(--g4);font-style:italic;}}

@media(max-width:800px){{.hero-pills{{display:none;}}.wrap{{padding:16px;}}.topbar-inner{{padding:0 16px;}}.hero{{padding:20px 16px;}}.modal{{margin:0;border-radius:0;max-height:100vh;}}}}
</style>
</head>
<body>

<!-- READER MODAL -->
<div class="modal-overlay" id="modal-overlay" onclick="closeReaderOnBg(event)">
  <div class="modal" id="modal">
    <div class="modal-header">
      <div class="modal-header-text">
        <div class="modal-source" id="modal-source"></div>
        <div class="modal-title" id="modal-title"></div>
      </div>
      <button class="modal-close" onclick="closeReader()">✕</button>
    </div>
    <div class="modal-ai" id="modal-ai">
      <div class="modal-ai-label">NRC Analysis</div>
      <div class="modal-summary" id="modal-summary"></div>
      <div class="modal-relevance" id="modal-relevance"></div>
    </div>
    <div class="modal-body">
      <div class="modal-body-text" id="modal-body-text"></div>
    </div>
    <div class="modal-footer">
      <a href="#" id="modal-source-link" target="_blank">View Original Source ↗</a>
      <span class="modal-paywall-note" id="modal-paywall-note"></span>
    </div>
  </div>
</div>

<header class="topbar">
  <div class="prog-wrap" id="prog"><div class="prog-fill" id="prog-fill"></div></div>
  <div class="topbar-inner">
    <div class="tb-brand">
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
    <div class="hero-title">Daily Market<br><em>Intelligence Brief</em></div>
    <div class="hero-pills">
      <div class="hpill"><div class="hpill-val">{len(today)}</div><div class="hpill-lbl">Articles</div></div>
      <div class="hpill"><div class="hpill-val">{data_pts}</div><div class="hpill-lbl">Data Points</div></div>
      <div class="hpill"><div class="hpill-val" style="color:#5ecf9e">{bullish}</div><div class="hpill-lbl">Bullish</div></div>
      <div class="hpill"><div class="hpill-val" style="color:#e07060">{bearish}</div><div class="hpill-lbl">Bearish</div></div>
    </div>
  </div>
</div>

<div class="wrap">
  <div class="tab-pane on" id="tab-today">
    <div class="frow">
      <span class="flabel">Filter:</span>
      <div class="fchip on" onclick="filterSent('all',this)">All</div>
      <div class="fchip" onclick="filterSent('bullish',this)">● Bullish</div>
      <div class="fchip" onclick="filterSent('bearish',this)">● Bearish</div>
      <div class="fchip" onclick="filterSent('neutral',this)">● Neutral</div>
      <input class="fsearch" placeholder="Search…" id="search-today" oninput="applyFilters()">
    </div>
    <div class="cards" id="cards-today">{cards_html}</div>
    <div class="section-label">Market Data Snapshot — AI extracted from today's articles</div>
    <div class="snapshot">{snap_html}</div>
  </div>

  <div class="tab-pane" id="tab-archive">
    <div class="frow" style="margin-bottom:14px">
      <span class="flabel">Archive — {len(archive)} articles</span>
      <input class="fsearch" style="margin-left:auto" placeholder="Search archive…" id="search-arc" oninput="filterArc()">
    </div>
    <div class="arc-wrap">
      <table class="arc-table">
        <thead><tr>
          <th>Date</th><th>Source</th><th>Headline</th><th>Market</th><th>Asset</th>
          <th>Vacancy</th><th>Cap Rate</th><th>Rent</th><th>Deal</th><th>Sentiment</th>
        </tr></thead>
        <tbody id="arc-tbody">{arc_html}</tbody>
      </table>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ── TABS ──
function switchTab(n,btn){{
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.tb-nav button').forEach(b=>b.classList.remove('on'));
  document.getElementById('tab-'+n).classList.add('on');
  btn.classList.add('on');
}}

// ── FILTERS ──
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
  document.querySelectorAll('#arc-tbody tr').forEach(r=>{{r.style.display=!q||r.innerText.toLowerCase().includes(q)?'':'none';}});
}}

// ── READER MODAL ──
function openReader(id){{
  const el=document.getElementById('reader-'+id);
  if(!el)return;
  const title=el.dataset.title;
  const source=el.dataset.source;
  const date=el.dataset.date;
  const url=el.dataset.url;
  const body=el.dataset.body;
  const summary=el.dataset.summary;
  const relevance=el.dataset.relevance;

  document.getElementById('modal-title').textContent=title;
  document.getElementById('modal-source').textContent=source+' · '+date;
  document.getElementById('modal-summary').textContent=summary||'';
  document.getElementById('modal-relevance').textContent=relevance||'';
  document.getElementById('modal-source-link').href=url;

  const aiBlock=document.getElementById('modal-ai');
  aiBlock.style.display=(summary||relevance)?'':'none';

  if(body&&body.trim().length>100){{
    document.getElementById('modal-body-text').textContent=body;
    document.getElementById('modal-paywall-note').textContent='';
  }}else{{
    document.getElementById('modal-body-text').textContent='Full article text could not be retrieved — this article may be behind a paywall.';
    document.getElementById('modal-paywall-note').textContent='Visit the original source to read the full article.';
  }}

  document.getElementById('modal-overlay').classList.add('open');
  document.body.style.overflow='hidden';
}}

function closeReader(){{
  document.getElementById('modal-overlay').classList.remove('open');
  document.body.style.overflow='';
}}

function closeReaderOnBg(e){{
  if(e.target===document.getElementById('modal-overlay'))closeReader();
}}

document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeReader();}});

// ── TOAST ──
function toast(msg,ms=4000){{
  const el=document.getElementById('toast');
  el.innerHTML=msg;el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'),ms);
}}

// ── RERUN ──
async function rerun(){{
  const GITHUB_USER='Lukemckenzie2026';
  const GITHUB_REPO='nrc-news';
  const TOKEN='{GITHUB_PAT}';
  if(!TOKEN||TOKEN==='{GITHUB_PAT}'||TOKEN==='NOT_SET'){{
    toast('⚠ Rerun not configured. See README to add your GitHub PAT.',7000);
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
      const tick=setInterval(()=>{{pct=Math.min(pct+Math.random()*1.5,90);fill.style.width=pct+'%';}},3000);
      toast('✓ Workflow triggered — takes ~3–4 min. Page reloads when done.',7000);
      await new Promise(r=>setTimeout(r,20000));
      for(let i=0;i<40;i++){{
        await new Promise(r=>setTimeout(r,8000));
        try{{
          const r2=await fetch(`https://api.github.com/repos/${{GITHUB_USER}}/${{GITHUB_REPO}}/actions/runs?per_page=1`,{{headers:{{'Authorization':`Bearer ${{TOKEN}}`,'Accept':'application/vnd.github+json'}}}});
          const d=await r2.json();
          const run=d.workflow_runs?.[0];
          if(run&&run.status==='completed'){{clearInterval(tick);fill.style.width='100%';toast('✓ Done — reloading…',2500);setTimeout(()=>location.reload(),2600);return;}}
        }}catch(_){{}}
      }}
      clearInterval(tick);
      toast('Workflow still running — reload in a few minutes.',5000);
      btn.disabled=false;btn.textContent='↻ Rerun';prog.classList.remove('show');fill.style.width='0%';
    }}else{{
      toast(`⚠ GitHub returned ${{res.status}}. Check your PAT has workflow permissions.`,8000);
      btn.disabled=false;btn.textContent='↻ Rerun';prog.classList.remove('show');fill.style.width='0%';
    }}
  }}catch(e){{
    toast('⚠ Error: '+e.message,6000);
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
    print(f"\n{'='*60}\nNRC Scraper — {today_str}\n{'='*60}\n")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # 1. Scrape headlines from all sources
    all_headlines = []
    for source in SOURCES:
        print(f"Scraping: {source['name']}")
        all_headlines.extend(scrape_headlines(source))
        time.sleep(1)
    print(f"\nTotal candidates: {len(all_headlines)}")

    # 2. Fetch full article text for ALL candidates
    print("\nFetching full article text…")
    for i, a in enumerate(all_headlines):
        body = fetch_article_text(a["url"])
        a["body"] = body
        if (i+1) % 10 == 0:
            print(f"  {i+1}/{len(all_headlines)} fetched")
        time.sleep(0.3)

    # 3. Filter using title + article text
    print("\nFiltering with Claude (using full article text)…")
    relevant = filter_with_claude(client, all_headlines)

    # Re-attach body text to filtered articles
    body_map = {a["url"]: a.get("body","") for a in all_headlines}
    for a in relevant:
        a["body"] = body_map.get(a["url"],"")

    # 4. Extract structured market data from full text
    print(f"\nExtracting market data from {len(relevant)} articles…")
    enriched = []
    for i, a in enumerate(relevant):
        print(f"  [{i+1}/{len(relevant)}] {a['title'][:55]}…")
        data = extract_market_data(client, a)
        enriched.append({
            **a, **data,
            "date": today_str,
            "id": hashlib.md5(a["url"].encode()).hexdigest()[:10]
        })
        time.sleep(0.5)

    # 5. Archive
    archive = load_archive()
    existing = {a["url"] for a in archive}
    new_arts = [a for a in enriched if a["url"] not in existing]
    full_archive = new_arts + archive
    save_archive(full_archive)
    print(f"\n  {len(new_arts)} new → {len(full_archive)} total in archive")

    # 6. Generate dashboard
    print("\nGenerating HTML dashboard…")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
        f.write(generate_html(enriched, full_archive, today_str))

    print(f"\n{'='*60}")
    print(f"Done → docs/index.html")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
