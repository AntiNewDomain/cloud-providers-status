# Cloud Providers Status Monitor

A free, lightweight monitor that checks the **official public status pages** of major US-based cloud providers and shows a live dashboard.

**Live Dashboard:** https://antinewdomain.github.io/cloud-providers-status/

## Providers Monitored

| Provider              | Source Type      | Official Endpoint |
|-----------------------|------------------|-------------------|
| Cloudflare            | JSON API         | cloudflarestatus.com/api/v2/summary.json |
| Amazon Web Services   | RSS              | status.aws.amazon.com/rss/all.rss |
| Microsoft Azure       | RSS              | rssfeed.azure.status.microsoft/en-us/status/feed/ |
| Google Cloud          | Atom             | status.cloud.google.com/en/feed.atom |
| GitHub                | JSON API         | githubstatus.com/api/v2/summary.json |
| DigitalOcean          | JSON API         | status.digitalocean.com/api/v2/summary.json |
| Oracle Cloud          | JSON API         | ocistatus.oraclecloud.com/api/v2/status.json |
| Microsoft 365 Admin Center | RSS       | status.cloud.microsoft/api/feed/mac |

Only official public sources are used. No third-party status aggregators. No China-based providers are included.

## Features

- Checks every **15 minutes** automatically
- Live dashboard on GitHub Pages
- Detects status changes
- Optional Discord alerts for massive outages only (plus one message when a massive outage clears)
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

Once added, you will receive a Discord message only when a provider has a massive outage (major/critical), and one message when it clears. Minor or degraded incidents do not alert.

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
- Feed providers are judged on their newest item only, and only if it is recent (under 12 hours) and unresolved — older feed entries cannot keep a provider stuck on outage after it resolved.
- Microsoft 365 / Outlook / Teams limitation: Microsoft publishes no anonymous public incident feed for Microsoft 365. The feed listed above reports only whether the Microsoft 365 Admin Center itself is Available; it did not list the Nov 12–14, 2026 Outlook/Teams outage (MO1550821 / EX1550543), and it never triggers a massive-outage alert. Full Microsoft 365 service health needs a tenant login.
- Fastly is intentionally excluded: its status API returns HTTP 403 from GitHub Actions-style runners.
- GitHub Actions scheduled runs are best-effort and can lag; the dashboard timestamp shows the last completed run.
- The check interval can be changed in the workflow file if needed.
