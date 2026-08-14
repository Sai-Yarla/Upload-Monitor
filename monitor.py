#!/usr/bin/env python3
"""
Social Media Post Monitor
--------------------------
Watches an Instagram account and a TikTok account for new posts/videos
and sends you an email as soon as one appears.

Usage:
    python monitor.py            # runs forever, checking every CHECK_INTERVAL_MINUTES
    python monitor.py --once     # runs a single check and exits (good for cron/Task Scheduler)

Setup:
    1. pip install -r requirements.txt
    2. Copy .env.example to .env and fill in your details
    3. Test it:  python monitor.py --once
"""

import os
import re
import json
import time
import smtplib
import argparse
from email.mime.text import MIMEText
from datetime import datetime, timezone

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env loading is optional if you set real environment variables instead

# ---------------------------------------------------------------------------
# Configuration (all overridable via .env / environment variables)
# ---------------------------------------------------------------------------
IG_USERNAME = os.getenv("TARGET_IG_USERNAME", "percyseries")
TT_USERNAME = os.getenv("TARGET_TT_USERNAME", "percyseries")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
TO_EMAIL = os.getenv("TO_EMAIL", EMAIL_ADDRESS)

CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))
STATE_FILE = os.getenv("STATE_FILE", "state.json")

# Optional: logging into Instagram makes checks noticeably more reliable,
# since Instagram heavily rate-limits anonymous requests. Use a throwaway
# or secondary account if you go this route, not your main one.
IG_LOGIN_USERNAME = os.getenv("IG_LOGIN_USERNAME")
IG_LOGIN_PASSWORD = os.getenv("IG_LOGIN_PASSWORD")


class InstagramRateLimitError(RuntimeError):
    pass


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# State handling — remembers the last post we saw for each platform
# ---------------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def send_email(subject, body):
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        print("[!] EMAIL_ADDRESS / EMAIL_APP_PASSWORD not set in .env — skipping send.")
        print(f"    Would have sent: {subject}\n    {body}")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = TO_EMAIL
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)
    print(f"[✓] Email sent: {subject}")


# ---------------------------------------------------------------------------
# Instagram checker (uses the instaloader library)
# ---------------------------------------------------------------------------
def check_instagram(state):
    """Returns (found_new, post_url) — updates state in place if a new post is found."""
    try:
        import instaloader

        class FailFastRateController(instaloader.RateController):
            def sleep(self, secs):
                raise InstagramRateLimitError(f"Instagram rate limited; refusing to wait {secs:.0f} seconds")

        L = instaloader.Instaloader(
            sleep=False,
            quiet=True,
            max_connection_attempts=1,
            request_timeout=20,
            rate_controller=lambda ctx: FailFastRateController(ctx),
        )
        if IG_LOGIN_USERNAME and IG_LOGIN_PASSWORD:
            try:
                L.login(IG_LOGIN_USERNAME, IG_LOGIN_PASSWORD)
            except Exception as e:
                print(f"[!] Instagram login failed, continuing anonymously: {e}")

        profile = instaloader.Profile.from_username(L.context, IG_USERNAME)
        latest = next(profile.get_posts(), None)
        if latest is None:
            return False, None

        if state.get("instagram") != latest.shortcode:
            state["instagram"] = latest.shortcode
            return True, f"https://www.instagram.com/p/{latest.shortcode}/"
        return False, None

    except InstagramRateLimitError as e:
        print(f"[!] Instagram check skipped: {e}")
        return False, None
    except Exception as e:
        print(f"[!] Instagram check failed: {e}")
        return False, None


# ---------------------------------------------------------------------------
# TikTok checker (scrapes the public profile page's embedded JSON)
# ---------------------------------------------------------------------------
def check_tiktok(state):
    try:
        url = f"https://www.tiktok.com/@{TT_USERNAME}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        data = _extract_tiktok_json(resp.text)
        if not data:
            print("[!] Could not find TikTok's embedded data blob (page layout may have changed).")
            return False, None

        items = _find_item_list(data)
        if not items:
            return False, None

        latest = items[0]
        video_id = latest.get("id")
        if not video_id:
            return False, None

        if state.get("tiktok") != video_id:
            state["tiktok"] = video_id
            return True, f"https://www.tiktok.com/@{TT_USERNAME}/video/{video_id}"
        return False, None

    except Exception as e:
        print(f"[!] TikTok check failed: {e}")
        return False, None


def _extract_tiktok_json(html):
    """TikTok embeds page data in a <script> tag; the id has changed over time,
    so we try the current one plus an older fallback."""
    for marker in ("__UNIVERSAL_DATA_FOR_REHYDRATION__", "SIGI_STATE"):
        match = re.search(rf'<script id="{marker}"[^>]*>(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
    return None


def _find_item_list(data):
    """Digs through TikTok's nested JSON to find the newest videos first."""
    try:
        scopes = data.get("__DEFAULT_SCOPE__", {})
        items = scopes.get("webapp.user-detail", {}).get("userInfo", {}).get("itemList")
        if items:
            return sorted(items, key=lambda x: int(x.get("createTime", 0)), reverse=True)
    except Exception:
        pass
    try:
        item_module = data.get("ItemModule", {})
        items = list(item_module.values())
        if items:
            return sorted(items, key=lambda x: int(x.get("createTime", 0)), reverse=True)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run_check_cycle():
    state = load_state()
    found_something = False

    found, url = check_instagram(state)
    if found:
        send_email(
            f"New Instagram post from @{IG_USERNAME}",
            f"New post detected:\n{url}\n\nChecked at {datetime.now(timezone.utc).isoformat()}",
        )
        found_something = True

    found, url = check_tiktok(state)
    if found:
        send_email(
            f"New TikTok video from @{TT_USERNAME}",
            f"New video detected:\n{url}\n\nChecked at {datetime.now(timezone.utc).isoformat()}",
        )
        found_something = True

    # Always stamp + save, even with no new posts. This guarantees state.json
    # changes on every run, which the GitHub Actions workflow commits — that
    # small commit is what keeps GitHub from auto-disabling the scheduled
    # workflow after 60 days of repo "inactivity."
    state["last_checked_utc"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    if not found_something:
        print(f"[{datetime.now().isoformat()}] No new posts.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single check and exit")
    args = parser.parse_args()

    if args.once:
        run_check_cycle()
        return

    print(
        f"Monitoring @{IG_USERNAME} (Instagram) and @{TT_USERNAME} (TikTok) "
        f"every {CHECK_INTERVAL_MINUTES} minutes. Press Ctrl+C to stop."
    )
    while True:
        run_check_cycle()
        time.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
