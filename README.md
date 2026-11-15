# Cloud Providers Status Monitor

Free, always-on monitor for the major cloud providers using **only official status sources**.

**Providers monitored:**
- Cloudflare (JSON API)
- Amazon Web Services (official RSS)
- Microsoft Azure (official RSS)
- Google Cloud (official Atom)

## Features
- Runs every 15 minutes via GitHub Actions
- Detects real status changes
- Sends Discord alerts when something changes
- Live dashboard on GitHub Pages
- Completely free

## Setup (already done for most parts)

1. **Add your Discord webhook**
   - Go to: https://github.com/AntiNewDomain/cloud-providers-status/settings/secrets/actions
   - Click **New repository secret**
   - Name: `DISCORD_WEBHOOK`
   - Value: your Discord webhook URL

2. **Enable GitHub Pages** (for the dashboard)
   - Go to: Settings → Pages
   - Source: Deploy from a branch
   - Branch: `main` / folder: `/docs`
   - Save

3. The first run will happen automatically on the schedule, or you can trigger it manually under the **Actions** tab.

Dashboard will be available at:  
https://antinewdomain.github.io/cloud-providers-status/

## How it works
The workflow runs `scripts/check.py`, which fetches the official endpoints, compares with the previous state, writes `status.json`, and optionally sends a Discord message.

You can change the schedule in `.github/workflows/monitor.yml`.
