# Cloud Providers Status Monitor

A free, lightweight monitor that checks the **official public status pages** of major cloud providers and shows a live dashboard.

**Live Dashboard:** https://antinewdomain.github.io/cloud-providers-status/

## Providers Monitored

| Provider              | Source Type      | Official Endpoint |
|-----------------------|------------------|-------------------|
| Cloudflare            | JSON API         | cloudflarestatus.com/api/v2/summary.json |
| Amazon Web Services   | RSS              | status.aws.amazon.com/rss/all.rss |
| Microsoft Azure       | RSS              | rssfeed.azure.status.microsoft |
| Google Cloud          | Atom             | status.cloud.google.com/en/feed.atom |

Only official public sources are used. No third-party status aggregators.

## Features

- Checks every **15 minutes** automatically
- Live dashboard on GitHub Pages
- Detects status changes
- Optional Discord alerts when status changes
- Completely free (runs on GitHub Actions)
- Independent of the providers being monitored

## Current Status

The monitor is already deployed and running.  
You only need to complete the optional Discord alert setup if you want notifications.

### Optional: Enable Discord Alerts

1. Create a Discord webhook in your server (Server Settings → Integrations → Webhooks)
2. Go to [Repository Secrets](https://github.com/AntiNewDomain/cloud-providers-status/settings/secrets/actions)
3. Click **New repository secret**
4. Name: `DISCORD_WEBHOOK`
5. Paste your webhook URL and save

Once added, you will receive a Discord message whenever a provider status changes.

## Manual Run

You can trigger a check immediately:

1. Go to the [Actions tab](https://github.com/AntiNewDomain/cloud-providers-status/actions)
2. Select **Cloud Status Monitor**
3. Click **Run workflow**

## Files

- `.github/workflows/monitor.yml` — scheduled workflow
- `scripts/check.py` — status checker script
- `docs/` — dashboard (GitHub Pages)
- `status.json` — latest status data

## Notes

- This uses provider-reported public status only. It is not independent uptime probing.
- Account-specific health events (AWS Health, Azure Service Health, etc.) are not included.
- The check interval can be changed in the workflow file if needed.
