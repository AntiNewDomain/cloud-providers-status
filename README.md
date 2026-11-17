# Cloud Providers Status Monitor

A free, lightweight monitor that checks the **official public status pages** of major US-based cloud providers and shows a live dashboard.

**Live Dashboard:** https://antinewdomain.github.io/cloud-providers-status/

## Providers Monitored

| Provider | Source Type | Official Endpoint |
|----------|-------------|-------------------|
| Cloudflare | JSON API | cloudflarestatus.com/api/v2/summary.json |
| Amazon Web Services | RSS | status.aws.amazon.com/rss/all.rss |
| Microsoft Azure | RSS | rssfeed.azure.status.microsoft/en-us/status/feed/ |
| Google Cloud | Atom | status.cloud.google.com/en/feed.atom |
| DigitalOcean | JSON API | status.digitalocean.com/api/v2/summary.json |
| Oracle Cloud | JSON API | ocistatus.oraclecloud.com/api/v2/status.json |
| Microsoft 365 (Consumer) | JSON API | status.cloud.microsoft/api/posts/m365Consumer |
| @MSFT365Status on X | Third-party RSS mirrors | See "Known limitations" below |

Microsoft 365 (Consumer) covers the consumer workloads Microsoft publishes through that endpoint — Microsoft 365 (Consumer), Copilot, Outlook.com, and Microsoft Teams Free. It is separate from tenant-specific Microsoft 365 business health, which still requires an administrator sign-in.

Only official public sources are used, except for the @MSFT365Status X posts, which come through third-party mirrors (see below). No China-based providers are included.

## How It Runs

- An external dispatcher, **cron-job.org**, starts the workflow **every 15 minutes** through `workflow_dispatch`.
- The workflow has **no native GitHub schedule block**. It was removed in PR #3 because GitHub's built-in scheduler was skipping runs. The triggers are `workflow_dispatch` plus `push` to `scripts/check.py` or the workflow file itself.
- Each run checks every provider, writes `status.json` (root) and `docs/status.json`, and publishes to GitHub Pages. Runs are serialized (one at a time) so an older run can never overwrite a newer result, and each run has a 10-minute timeout.
- The dashboard refreshes from `status.json` and shows the last completed run's timestamp. Expect up to 15 minutes of lag by design.

## How Status Is Decided

- **Statuspage providers** (Cloudflare, DigitalOcean, Oracle): the provider's own indicator decides. `major` or `critical` means outage; `minor` means degraded.
- **Feed providers** (AWS, Azure, Google Cloud): only the **newest** feed item decides, and only if it is recent (under 12 hours) and unresolved. Older entries cannot keep a provider stuck on outage after it resolved. The last 3 items are still kept so the dashboard can show recent history — they do not affect the status.
- **Feed wording:** an item is read as an outage when its title or summary contains "outage", "disruption", "unavailable", or "major". It is read as degraded when it contains "degraded", "elevated", "increased error", or "impact". See "Known limitations" for what that misses.
- **Microsoft 365 (Consumer):** the aggregate card reports the worst status across the consumer workloads; product cards use their own workload records.
- A provider that cannot be reached, or whose check fails, shows as `error` — never as a stale copy of its last good state.

## Major-Outage Banner

When any provider is in a major outage (status `outage`), a red banner appears at the **very top of the dashboard**, above the title and every card, naming the provider and its incident. It shows **only** for a major outage — it stays hidden for operational, degraded, error, and stale states — and it scans every provider, not just the grouped cards, so nothing major can hide.

## Alerts

### Discord

A Discord message is sent **only** when a provider enters a massive outage, plus one message when it clears. Minor or degraded incidents do not alert.

Setup:

1. Create a Discord webhook in your server (Server Settings → Integrations → Webhooks)
2. Go to [Repository Secrets](https://github.com/AntiNewDomain/cloud-providers-status/settings/secrets/actions)
3. Click **New repository secret**
4. Name: `DISCORD_WEBHOOK`
5. Paste your webhook URL and save

A `test_discord` workflow input is being added so the stored webhook can be tested on demand with a clearly labeled test message (it checks for a successful delivery, it does not reuse the outage alert format).

### Independent DM watch

Separately from this repository, a 15-minute watch checks the official sources directly and sends a direct message on a massive outage. It does not depend on GitHub, cron-job.org, or this dashboard, so it still alerts if the pipeline itself stops. It also includes a **staleness watchdog**: if the dashboard has not updated in over 40 minutes, it sends one alert, and one recovery message when updates resume.

## Manual Run

You can trigger a check immediately:

1. Go to the [Actions tab](https://github.com/AntiNewDomain/cloud-providers-status/actions)
2. Select **Cloud Status Monitor**
3. Click **Run workflow**

## Files

- `.github/workflows/monitor-v2.yml` — workflow (triggered by cron-job.org via `workflow_dispatch`, plus `push`)
- `scripts/check.py` — status checker
- `docs/` — dashboard (GitHub Pages)
- `status.json` — latest status data (also used to detect status changes between runs)

## Known Limitations

- **@MSFT365Status on X is third-party mirrors only.** The posts are fetched through independent mirrors (FxEmbed, Nitter instances, RSSHub). They are not an official feed, and they may fail. The dashboard labels them as retrieved through a third-party mirror.
- **Enterprise Microsoft 365 outages are not covered.** Microsoft publishes no anonymous public incident feed for enterprise Microsoft 365. This monitor uses the consumer endpoint and the @MSFT365Status posts; it did not list the Nov 12–14, 2026 Outlook/Teams outage (MO1550821 / EX1550543). Full Microsoft 365 service health needs a tenant login.
- **Keyword blind spot.** An incident worded "Increased error rates" matches the degraded keywords, not the outage keywords — so a genuinely major incident phrased that way shows as degraded, triggers no massive alert, and shows no top banner. The wording lists are deliberately kept narrow to avoid false positives.
- **Fastly is intentionally excluded:** its status API returns HTTP 403 from GitHub Actions-style runners.
- **Single dispatcher.** cron-job.org is the only trigger. If it stops dispatching, the dashboard goes stale and the independent DM watch's staleness watchdog is the backstop that reports it.
- This uses provider-reported public status only. It is not independent uptime probing.
- Account-specific health events (AWS Health, Azure Service Health, etc.) are not included.
