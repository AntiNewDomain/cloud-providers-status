#!/usr/bin/env python3
"""
Cloud Providers Status Checker
Checks official status pages for US-based cloud providers and sends a
Discord alert ONLY on a massive outage (or when one clears).
Writes status.json.

Providers: Cloudflare, AWS, Microsoft Azure, Google Cloud,
DigitalOcean, Oracle Cloud, plus Microsoft 365 Admin Center (limited —
see below).

Fixes vs the original version:
- Feed providers (AWS/Azure/GCP) used to flag "outage" forever: they took
  the first 8 feed items and flagged any with "disruption" in the title,
  with no date or resolved check, so Sep 15 entries kept AWS stuck on
  outage long after US-EAST-1 was resolved. Now only the NEWEST feed item
  counts, it must be recent (<12h) and unresolved.
- Discord used to alert on ANY status change (including minor/degraded).
  Now it alerts only when a provider becomes massive, plus one message
  when a massive outage clears. Minor/degraded changes do not alert.

Microsoft 365 / Outlook / Teams limitation:
Microsoft publishes NO anonymous public incident feed for Microsoft 365.
The only public RSS (status.cloud.microsoft/api/feed/mac) reports whether
the Microsoft 365 Admin Center itself is Available — it did NOT list the
Nov 12-14, 2026 Outlook/Teams outage (MO1550821 / EX1550543). It is
included here as "m365_admin_center" for what it is, and it NEVER counts
as massive on its own. Full Microsoft 365 service health needs a tenant
login (Microsoft Graph ServiceHealth.Read.All).

Fastly is intentionally excluded: its status API returns HTTP 403 from
GitHub Actions-style runners, so it cannot be checked reliably.
No China-based providers are included by design.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime

import requests
import feedparser

# Official sources only
SOURCES = {
    "cloudflare": {
        "name": "Cloudflare",
        "url": "https://www.cloudflarestatus.com/api/v2/summary.json",
        "type": "statuspage",
    },
    "aws": {
        "name": "Amazon Web Services",
        "url": "https://status.aws.amazon.com/rss/all.rss",
        "type": "rss",
    },
    "azure": {
        "name": "Microsoft Azure",
        "url": "https://rssfeed.azure.status.microsoft/en-us/status/feed/",
        "type": "rss",
    },
    "gcp": {
        "name": "Google Cloud",
        "url": "https://status.cloud.google.com/en/feed.atom",
        "type": "atom",
    },
    "digitalocean": {
        "name": "DigitalOcean",
        "url": "https://status.digitalocean.com/api/v2/summary.json",
        "type": "statuspage",
    },
    "oracle": {
        "name": "Oracle Cloud",
        "url": "https://ocistatus.oraclecloud.com/api/v2/status.json",
        "type": "statuspage",
    },
    "m365_admin_center": {
        "name": "Microsoft 365 Admin Center",
        "url": "https://status.cloud.microsoft/api/feed/mac",
        "type": "rss",
    },
}

RECENT = timedelta(hours=12)
STATUS_FILE = Path("status.json")
DOCS_STATUS = Path("docs/status.json")


def _parse_date(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fetch_statuspage(key):
    info = SOURCES[key]
    r = requests.get(info["url"], timeout=20)
    r.raise_for_status()
    data = r.json()

    indicator = data.get("status", {}).get("indicator", "unknown")
    description = data.get("status", {}).get("description", "")

    # Only major/critical is massive. minor = degraded, none = operational.
    if indicator == "none":
        status = "operational"
    elif indicator in ("major", "critical"):
        status = "outage"
    elif indicator == "minor":
        status = "degraded"
    else:
        status = indicator

    incidents = []
    for inc in data.get("incidents", [])[:5]:
        incidents.append({
            "name": inc.get("name"),
            "status": inc.get("status"),
            "impact": inc.get("impact"),
            "updated": inc.get("updated_at"),
        })

    return {
        "provider": key,
        "name": info["name"],
        "status": status,
        "description": description,
        "indicator": indicator,
        "incidents": incidents,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": info["url"],
    }


def fetch_rss_or_atom(key):
    info = SOURCES[key]
    feed = feedparser.parse(info["url"])

    # Only the NEWEST item decides the status, and only if it is recent
    # and unresolved. Old entries (e.g. Sep 15 AWS items still in the feed)
    # must not keep a provider stuck on outage after it resolved.
    entries = feed.entries[:1]
    active = []
    for entry in entries:
        title = entry.get("title", "")
        summary = entry.get("summary", entry.get("description", ""))
        published = entry.get("published", entry.get("updated", ""))

        lower = (title + " " + summary).lower()
        if any(w in lower for w in ["resolved", "operating normally", "all systems operational"]):
            severity = "resolved"
        elif any(w in lower for w in ["outage", "disruption", "unavailable", "major"]):
            severity = "outage"
        elif any(w in lower for w in ["degraded", "elevated", "increased error", "impact"]):
            severity = "degraded"
        else:
            severity = "info"

        active.append({
            "title": title,
            "summary": summary[:400] + ("..." if len(summary) > 400 else ""),
            "published": published,
            "severity": severity,
            "link": entry.get("link", ""),
        })

    overall = "operational"
    if active:
        newest = active[0]
        published_at = _parse_date(newest["published"])
        recent = published_at is not None and (
            datetime.now(timezone.utc) - published_at) <= RECENT
        if newest["severity"] == "outage" and recent:
            overall = "outage"
        elif newest["severity"] == "degraded" and recent:
            overall = "degraded"
        elif newest["severity"] == "resolved":
            overall = "operational"

    result = {
        "provider": key,
        "name": info["name"],
        "status": overall,
        "description": f"Latest item from official feed ({len(active)} recent)",
        "incidents": active,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": info["url"],
    }

    # Microsoft 365 Admin Center feed: it reports only whether the Admin
    # Center itself is Available. It is NOT Outlook/Teams health and must
    # never trigger a massive-outage alert on its own.
    if key == "m365_admin_center":
        result["status"] = "operational" if overall != "outage" else "degraded"
        result["description"] = (
            "Admin Center availability only — this feed does NOT cover "
            "Outlook/Teams/Exchange Online incidents."
        )

    return result


def load_previous():
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except Exception:
            pass
    return {}


def save_status(data):
    STATUS_FILE.write_text(json.dumps(data, indent=2))
    # Also copy to docs for GitHub Pages
    DOCS_STATUS.parent.mkdir(parents=True, exist_ok=True)
    DOCS_STATUS.write_text(json.dumps(data, indent=2))


def send_discord(webhook, message):
    if not webhook:
        print("No DISCORD_WEBHOOK set — skipping alert")
        return
    try:
        requests.post(webhook, json={"content": message}, timeout=10)
        print("Discord alert sent")
    except Exception as e:
        print(f"Failed to send Discord alert: {e}")


def is_massive(result):
    """Massive = a major/critical outage, not minor/degraded."""
    if result["provider"] == "m365_admin_center":
        return False
    return result.get("status") == "outage"


def main():
    previous = load_previous()
    results = {}

    for key, info in SOURCES.items():
        try:
            if info["type"] == "statuspage":
                results[key] = fetch_statuspage(key)
            else:
                results[key] = fetch_rss_or_atom(key)
        except Exception as e:
            results[key] = {
                "provider": key,
                "name": info["name"],
                "status": "error",
                "description": str(e),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

    # Detect massive-outage transitions only (not every status change).
    prev_providers = previous.get("providers", {}) if isinstance(previous, dict) else {}
    new_massive = []
    cleared_massive = []
    for key, current in results.items():
        prev = prev_providers.get(key, {})
        was_massive = prev.get("status") == "outage" and key != "m365_admin_center"
        now_massive = is_massive(current)
        if now_massive and not was_massive:
            new_massive.append(current)
        elif was_massive and not now_massive:
            cleared_massive.append(current)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "providers": results,
    }

    save_status(payload)

    messages = []
    for current in new_massive:
        detail = current.get("description", "")
        incidents = current.get("incidents") or []
        first = incidents[0] if incidents else {}
        title = first.get("name") or first.get("title") or ""
        messages.append(
            f"🚨 **MASSIVE OUTAGE: {current['name']}**\n"
            f"{title}\n{detail}\n"
            "Many websites/services running on or behind this provider may be down."
        )
    for current in cleared_massive:
        messages.append(f"✅ **{current['name']}** massive outage has cleared.")

    if messages:
        msg = "\n\n".join(messages)
        msg += "\n\nDashboard: https://antinewdomain.github.io/cloud-providers-status/"
        send_discord(os.environ.get("DISCORD_WEBHOOK"), msg)
        print("Massive-outage changes detected:")
        for m in messages:
            print(" -", m.splitlines()[0])
    else:
        print("No massive-outage changes detected.")

    print("Status written to status.json")


if __name__ == "__main__":
    main()
