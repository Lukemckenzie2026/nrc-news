# NRC Market Intelligence — Setup Guide

---

## Step 1: Create a GitHub Account + Repo

1. Go to [github.com](https://github.com) → Sign up (free)
2. Click **+** → **New repository**
   - Name: `nrc-news`
   - Visibility: **Public** ← required for free GitHub Pages
   - Click **Create repository**
3. Upload all files from this zip into the repo (drag and drop onto the page)

---

## Step 2: Enable GitHub Pages

1. In your repo → **Settings** → **Pages** (left sidebar)
2. Source: **Deploy from a branch**
3. Branch: `main` · Folder: `/docs`
4. Click **Save**
5. Wait ~60 seconds → your link appears: `https://YOURUSERNAME.github.io/nrc-news`

---

## Step 3: Add Your Anthropic API Key as a Secret

1. Get a key at [console.anthropic.com](https://console.anthropic.com) → API Keys → Create Key
2. In your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
   - Name: `ANTHROPIC_API_KEY`
   - Value: `sk-ant-...` (your key)
4. Click **Add secret**

---

## Step 4: Test It (First Run)

1. In your repo → **Actions** tab
2. Click **NRC Daily Scraper** (left sidebar)
3. Click **Run workflow** → **Run workflow**
4. Watch it run (~3–4 minutes)
5. Open your GitHub Pages link — dashboard is live

After this, it runs automatically every weekday at 7 AM ET. No terminal needed.

---

## Step 5: Enable the Rerun Button (Optional)

The **↻ Rerun** button on the dashboard triggers the workflow from the browser.
It needs a GitHub Personal Access Token (PAT):

1. GitHub → your profile photo → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. Click **Generate new token (classic)**
   - Note: `NRC Rerun`
   - Expiration: 90 days (or No expiration)
   - Scopes: check **workflow** only
3. Copy the token (starts with `ghp_...`)
4. Open `scripts/scraper.py` — find these three lines near the top of the `rerun()` JS function:
   ```
   const GITHUB_USER='{GITHUB_USER}';
   const GITHUB_REPO='{GITHUB_REPO}';
   const TOKEN='{GITHUB_PAT}';
   ```
5. Replace with your values:
   ```
   const GITHUB_USER='lukem';
   const GITHUB_REPO='nrc-news';
   const TOKEN='ghp_xxxxxxxxxxxx';
   ```
6. Run the scraper once to regenerate `docs/index.html`, then push to GitHub

---

## Daily Customization

Edit the top of `scripts/scraper.py`:
- **`SOURCES`** — add/remove news sites
- **`RELEVANCE_PROMPT`** — what counts as NRC-relevant (plain English)
- **`EXTRACTION_PROMPT`** — what data fields to extract (plain English)

After any changes: run `python scripts/scraper.py` locally (with `ANTHROPIC_API_KEY` set),
then `git add docs/ && git commit -m "update" && git push`.

Or just trigger via the Rerun button if Step 5 is set up.

---

## Schedule

Runs automatically Mon–Fri at 7 AM ET. To change the time,
edit `.github/workflows/daily.yml` → the `cron:` line.
Cron format: `"minute hour * * days"` (UTC time).
7 AM ET = `0 11 * * 1-5` (EST) or `0 12 * * 1-5` (EDT).
