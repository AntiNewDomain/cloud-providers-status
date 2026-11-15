#!/usr/bin/env python3
"""
Cloud Providers Status Checker
Checks official status pages for AWS, Cloudflare, Azure, Google Cloud.
Sends Discord alert on changes and writes status.json
"""

import os
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser

# Official sources only
SOURCES = {
    "cloudflare": {
        "name": "Cloudflare",
        "url": "https://www.cloudflarestatus.com/api/v2/summary.json",
        "type": "json",
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
}

STATUS_FILE = Path("status.json")
DOCS_STATUS = Path("docs/status.json")

def fetch_cloudflare():
    r = requests.get(SOURCES["cloudflare"]["url"], timeout=20)
    r.raise_for_status()
    data = r.json()

    indicator = data.get("status", {}).get("indicator", "unknown")
    description = data.get("status", {}).get("description", "")

    # Map Cloudflare indicators
    if indicator == "none":
        status = "operational"
    elif indicator in ("minor", "major", "critical"):
        status = "outage" if indicator in ("major", "critical") else "degraded"
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
        "provider": "cloudflare",
        "name": "Cloudflare",
        "status": status,
        "description": description,
        "indicator": indicator,
        "incidents": incidents,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCES["cloudflare"]["url"],
    }

def fetch_rss_or_atom(key):
    info = SOURCES[key]
    feed = feedparser.parse(info["url"])

    # Look for recent active issues
    active = []
    for entry in feed.entries[:8]:
        title = entry.get("title", "")
        summary = entry.get("summary", entry.get("description", ""))
        published = entry.get("published", entry.get("updated", ""))

        # Simple heuristics for severity
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

    # Overall status from newest non-resolved item
    overall = "operational"
    for item in active:
        if item["severity"] == "outage":
            overall = "outage"
            break
        if item["severity"] == "degraded" and overall != "outage":
            overall = "degraded"

    return {
        "provider": key,
        "name": info["name"],
        "status": overall,
        "description": f"Latest items from official feed ({len(active)} recent)",
        "incidents": active,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": info["url"],
    }

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

def main():
    previous = load_previous()
    results = {}
    changes = []

    # Cloudflare
    try:
        results["cloudflare"] = fetch_cloudflare()
    except Exception as e:
        results["cloudflare"] = {
            "provider": "cloudflare",
            "name": "Cloudflare",
            "status": "error",
            "description": str(e),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    # AWS, Azure, GCP via feeds
    for key in ("aws", "azure", "gcp"):
        try:
            results[key] = fetch_rss_or_atom(key)
        except Exception as e:
            results[key] = {
                "provider": key,
                "name": SOURCES[key]["name"],
                "status": "error",
                "description": str(e),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

    # Detect changes
    for key, current in results.items():
        prev = previous.get(key, {})
        prev_status = prev.get("status")
        curr_status = current.get("status")

        if prev_status and prev_status != curr_status:
            changes.append(
                f"**{current['name']}** changed: `{prev_status}` → `{curr_status}`\n"
                f"{current.get('description', '')}"
            )

        # Also alert on new high-severity incidents
        if curr_status in ("outage", "degraded") and prev_status not in ("outage", "degraded"):
            if key not in [c.split("**")[1] for c in changes if "**" in c]:
                changes.append(f"**{current['name']}** is now **{curr_status}**")

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "providers": results,
    }

    save_status(payload)

    if changes:
        msg = "🚨 **Cloud Status Alert**\n\n" + "\n\n".join(changes)
        msg += f"\n\nDashboard: https://antinewdomain.github.io/cloud-providers-status/"
        send_discord(os.environ.get("DISCORD_WEBHOOK"), msg)
        print("Changes detected:")
        for c in changes:
            print(" -", c)
    else:
        print("No status changes detected.")

    print("Status written to status.json")

if __name__ == "__main__":
    main()
