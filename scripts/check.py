#!/usr/bin/env python3
"""
Cloud Providers Status Checker
Checks official status pages for US-based cloud providers and sends a
Discord alert ONLY on a massive outage (or when one clears).
Writes status.json.

Providers: Cloudflare, AWS, Microsoft Azure, Google Cloud,
DigitalOcean, Oracle Cloud, plus Microsoft's public Microsoft 365 consumer
service-health API (including Copilot, Outlook.com, and Teams Free). Today's
@MSFT365Status posts are retrieved separately through a third-party RSS mirror.

Fixes vs the original version:
- Feed providers (AWS/Azure/GCP) used to flag "outage" forever: they took
  the first 8 feed items and flagged any with "disruption" in the title,
  with no date or resolved check, so Sep 15 entries kept AWS stuck on
  outage long after US-EAST-1 was resolved. Now only the NEWEST feed item
  counts, it must be recent (<12h) and unresolved.
- Discord used to alert on ANY status change (including minor/degraded).
  Now it alerts only when a provider becomes massive, plus one message
  when a massive outage clears. Minor/degraded changes do not alert.

Microsoft consumer monitoring:
The public status page exposes consumer workload data through
https://status.cloud.microsoft/api/posts/m365Consumer. This monitor uses
that official endpoint for Microsoft 365 (Consumer), Copilot, Outlook.com,
and Microsoft Teams Free. The aggregate consumer card reports the worst
status across returned consumer workloads; product cards use their own
workload records. This is separate from tenant-specific Microsoft 365
business health, which still requires an administrator sign-in.

Fastly is intentionally excluded: its status API returns HTTP 403 from
GitHub Actions-style runners, so it cannot be checked reliably.
No China-based providers are included by design.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import requests
import feedparser

# Provider status sources; Microsoft 365 X posts use a separate third-party feed mirror.
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
}

MICROSOFT_CONSUMER_URL = "https://status.cloud.microsoft/api/posts/m365Consumer"

# Free public X timeline sources, ordered by preference.
# FxEmbed documents RSS feeds for public X profiles. Nitter instances and
# RSSHub mirrors are independent fallbacks; all are third-party and may fail.
# Do not treat an unreachable source as evidence that no posts were published.
MICROSOFT_365_X_FEED_URLS = [
    "https://fxtwitter.com/MSFT365Status/feed.xml?count=50",
    "https://nitter.mie.foundation/MSFT365Status/rss",
    "https://nitter.mizuki.st/MSFT365Status/rss",
    "https://hub.slarker.me/twitter/user/MSFT365Status?count=30&includeReplies=0&includeRts=0&forceWebApi=1",
    "https://rsshub.rssforever.com/twitter/user/MSFT365Status?count=30&includeReplies=0&includeRts=0&forceWebApi=1",
    "https://rsshub.app/twitter/user/MSFT365Status?count=30&includeReplies=0&includeRts=0&forceWebApi=1",
]
CENTRAL_TZ = ZoneInfo("America/Chicago")


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain_text(value):
    parser = _HTMLText()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())


def fetch_microsoft_365_x_posts():
    """Fetch real @MSFT365Status posts and retain only posts dated today in Central Time."""
    checked_at = datetime.now(timezone.utc).isoformat()
    today_ct = datetime.now(CENTRAL_TZ).date()
    result = {
        "provider": "microsoft_365_x",
        "name": "Microsoft 365 Status — X Updates",
        "account": "@MSFT365Status",
        "status": "ok",
        "retrieval_status": "ok",
        "date_ct": today_ct.isoformat(),
        "timezone": "America/Chicago",
        "posts": [],
        "today_count": 0,
        "checked_at": checked_at,
        "source": None,
        "account_url": "https://x.com/MSFT365Status",
        "description": "Actual posts published today, Central Time. Retrieved through a third-party RSS mirror.",
    }

    feed = None
    feed_errors = []
    for feed_url in MICROSOFT_365_X_FEED_URLS:
        try:
            response = requests.get(
                feed_url,
                headers={"User-Agent": "CloudProvidersStatusMonitor/1.0"},
                timeout=12,
            )
            response.raise_for_status()
            candidate = feedparser.parse(response.content)
            if getattr(candidate, "bozo", False) and not candidate.entries:
                raise ValueError(f"invalid RSS: {candidate.bozo_exception}")
            if not getattr(candidate, "version", ""):
                raise ValueError("response was not a recognizable RSS/Atom feed")
            # A valid feed with zero entries is still a successful retrieval;
            # only then may the dashboard accurately say no posts were found.
            feed = candidate
            result["source"] = feed_url
            break
        except Exception as error:
            feed_errors.append(f"{feed_url}: {error}")
    if feed is None:
        raise RuntimeError("All public X feed mirrors failed: " + " | ".join(feed_errors))

    seen = set()
    posts = []
    for entry in feed.entries:
        published = entry.get("published") or entry.get("updated") or ""
        published_at = _parse_date(published)
        # Missing/invalid timestamps are excluded rather than guessed as today's posts.
        if published_at is None or published_at.astimezone(CENTRAL_TZ).date() != today_ct:
            continue

        raw_text = entry.get("title", "") or ""
        content_blocks = entry.get("content") or []
        if content_blocks:
            candidate = content_blocks[0].get("value", "")
            if len(candidate) > len(raw_text):
                raw_text = candidate
        summary = entry.get("summary", "") or ""
        if len(summary) > len(raw_text):
            raw_text = summary
        post_text = _plain_text(raw_text)
        link = str(entry.get("link", "") or "").strip()
        identity = link or str(entry.get("id", "") or "") or f"{published}|{post_text}"
        if not post_text or identity in seen:
            continue
        seen.add(identity)
        posts.append({
            "text": post_text,
            "published_at": published_at.astimezone(timezone.utc).isoformat(),
            "published_local": published_at.astimezone(CENTRAL_TZ).strftime("%I:%M %p CT").lstrip("0"),
            "link": link,
        })

    posts.sort(key=lambda item: item["published_at"], reverse=True)
    result["posts"] = posts[:20]
    result["today_count"] = len(result["posts"])
    return result


def microsoft_365_x_unavailable(error):
    """Keep X retrieval failure separate from Microsoft's actual service health."""
    checked_at = datetime.now(timezone.utc).isoformat()
    return {
        "provider": "microsoft_365_x",
        "name": "Microsoft 365 Status — X Updates",
        "account": "@MSFT365Status",
        "status": "unavailable",
        "retrieval_status": "unavailable",
        "date_ct": datetime.now(CENTRAL_TZ).date().isoformat(),
        "timezone": "America/Chicago",
        "posts": [],
        "today_count": 0,
        "checked_at": checked_at,
        "source": "; ".join(MICROSOFT_365_X_FEED_URLS),
        "account_url": "https://x.com/MSFT365Status",
        "description": f"X feed retrieval failed; no claim is made that there were no posts. {str(error)[:300]}",
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
    # Fetch with a bounded timeout first, then parse the bytes: feedparser's
    # own URL fetch has no timeout, so one hung feed could stall the whole
    # run until the workflow's 10-minute timeout kills it and nothing is
    # published. raise_for_status() deliberately turns an HTTP 404/500 into
    # a provider "error" instead of a silent "operational" with 0 incidents.
    response = requests.get(info["url"], timeout=20)
    response.raise_for_status()
    feed = feedparser.parse(response.content)

    # Only the NEWEST item decides the status, and only if it is recent
    # and unresolved. Old entries (e.g. Sep 15 AWS items still in the feed)
    # must not keep a provider stuck on outage after it resolved.
    # The last 3 items are still kept in "incidents" so the dashboard can
    # show recent history — they do not affect the status.
    entries = feed.entries[:3]
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
        "description": f"Latest items from official feed ({len(active)} recent)",
        "incidents": active,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": info["url"],
    }

    return result



def _microsoft_status(value):
    """Normalize Microsoft's public consumer-status labels."""
    value = str(value or "").strip().lower()
    if any(word in value for word in ("outage", "down", "unavailable")):
        return "outage"
    if any(word in value for word in ("degrad", "partial", "intermittent", "disruption")):
        return "degraded"
    if any(word in value for word in ("operational", "normal", "available", "healthy")):
        return "operational"
    return "unknown"


def fetch_microsoft_consumer():
    """Read Microsoft's public consumer service-health API (no tenant login)."""
    response = requests.get(MICROSOFT_CONSUMER_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        for key in ("value", "data", "posts", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if isinstance(payload, dict) and payload.get("ServiceDisplayName"):
        payload = [payload]
    if not isinstance(payload, list):
        raise ValueError("Unexpected Microsoft consumer status API response format")
    records = [item for item in payload if isinstance(item, dict)]
    if not records:
        raise ValueError("Microsoft consumer status API returned no service records")

    def display(item):
        return str(item.get("ServiceDisplayName") or "").strip().lower()

    def workload(item):
        return str(item.get("ServiceWorkloadName") or "").strip().lower()

    specs = {
        "m365_consumer": ("Microsoft 365 (Consumer)", lambda x:
            "microsoft 365 (consumer)" in display(x)
            or "microsoft 365 consumer" in display(x)
            or workload(x) in ("m365consumer", "microsoft365consumer")),
        "m365_copilot": ("Microsoft Copilot", lambda x:
            "copilot" in display(x) or "copilot" in workload(x)),
        "outlook_com": ("Outlook.com", lambda x:
            "outlook.com" in display(x) or "outlookconsumer" in workload(x)
            or workload(x) == "outlook"),
        "microsoft_teams": ("Microsoft Teams (Consumer / Free)", lambda x:
            ("teams" in display(x) and any(t in display(x) for t in ("free", "consumer", "personal")))
            or any(t in workload(x) for t in ("teamsfree", "teamsconsumer"))),
    }

    def updated(item):
        return _parse_date(item.get("LastUpdatedTime") or "") or datetime.min.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc).isoformat()
    output = {}
    for key, (name, matches) in specs.items():
        matched = sorted([x for x in records if matches(x)], key=updated, reverse=True)
        if key == "m365_consumer":
            statuses = [_microsoft_status(x.get("Status")) for x in records]
            known = [s for s in statuses if s != "unknown"]
            status = ("outage" if "outage" in known else
                      "degraded" if "degraded" in known else
                      "operational" if known else "unknown")
            affected = [x for x in records if _microsoft_status(x.get("Status")) in ("outage", "degraded")]
        elif matched:
            status = _microsoft_status(matched[0].get("Status"))
            affected = [x for x in matched if _microsoft_status(x.get("Status")) in ("outage", "degraded")]
        else:
            status, affected = "unknown", []

        incidents = [{
            "name": x.get("Title") or x.get("ServiceDisplayName") or name,
            "summary": (x.get("Message") or "")[:600],
            "status": x.get("Status"),
            "updated": x.get("LastUpdatedTime"),
        } for x in affected[:5]]

        if key != "m365_consumer" and not matched:
            description = "No separate component record was returned by Microsoft's public consumer status API."
        elif status == "unknown":
            description = "Microsoft returned an unrecognized or unavailable status value."
        elif status in ("degraded", "outage"):
            description = f"Microsoft's official consumer status reports {status}."
        else:
            description = "Microsoft's official consumer status reports this service operational."

        output[key] = {
            "provider": key, "name": name, "status": status,
            "description": description, "incidents": incidents,
            "checked_at": now, "source": MICROSOFT_CONSUMER_URL,
            "status_page": "https://status.cloud.microsoft/",
        }
    return output

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


DISCORD_TEST_MESSAGE = (
    "🧪 TEST — Cloud Status Monitor Discord webhook check. "
    "This is only a test; no outage is happening."
)


def test_discord_webhook(webhook):
    """One-off webhook check: post a labeled test message and verify HTTP 2xx.

    Returns 0 on delivery, 1 on failure. The response status is checked
    explicitly — send_discord() only prints "Discord alert sent" and never
    looks at the status, so a wrong webhook (HTTP 404) would otherwise
    look like success. Run with TEST_DISCORD=1 or TEST_DISCORD=true (set by
    the workflow's test_discord input); exits before any status check runs.
    """
    if not webhook:
        print("Discord test FAILED: no DISCORD_WEBHOOK set")
        return 1
    try:
        response = requests.post(
            webhook, json={"content": DISCORD_TEST_MESSAGE}, timeout=10
        )
    except Exception as e:
        print(f"Discord test FAILED: {e}")
        return 1
    if 200 <= response.status_code < 300:
        print(f"Discord test delivered (HTTP {response.status_code})")
        return 0
    print(f"Discord test FAILED: HTTP {response.status_code}")
    return 1


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
    return result.get("status") == "outage"


def main():
    # Discord webhook test mode: verify the stored secret delivers, then
    # exit before any status check runs. Set by the workflow's test_discord
    # input via the TEST_DISCORD env var.
    if os.environ.get("TEST_DISCORD", "").strip().lower() in ("1", "true"):
        raise SystemExit(test_discord_webhook(os.environ.get("DISCORD_WEBHOOK")))

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

    try:
        results.update(fetch_microsoft_consumer())
    except Exception as e:
        for key, name in (
            ("m365_consumer", "Microsoft 365 (Consumer)"),
            ("m365_copilot", "Microsoft Copilot"),
            ("outlook_com", "Outlook.com"),
            ("microsoft_teams", "Microsoft Teams (Consumer / Free)"),
        ):
            results[key] = {
                "provider": key, "name": name, "status": "error",
                "description": f"Microsoft consumer status API check failed: {e}",
                "incidents": [], "checked_at": datetime.now(timezone.utc).isoformat(),
                "source": MICROSOFT_CONSUMER_URL,
            }

    try:
        results["microsoft_365_x"] = fetch_microsoft_365_x_posts()
    except Exception as e:
        results["microsoft_365_x"] = microsoft_365_x_unavailable(e)

    # Detect massive-outage transitions only (not every status change).
    prev_providers = previous.get("providers", {}) if isinstance(previous, dict) else {}
    new_massive = []
    cleared_massive = []
    for key, current in results.items():
        prev = prev_providers.get(key, {})
        if key in ("m365_copilot", "outlook_com", "microsoft_teams"):
            continue
        was_massive = prev.get("status") == "outage"
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
