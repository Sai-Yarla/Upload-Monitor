# @percyseries Post Monitor

Checks the Instagram and TikTok accounts `@percyseries` on a schedule and emails you
as soon as a new post/video appears.

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 2. Configure email + accounts

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Then edit `.env` and fill in:

- `EMAIL_ADDRESS` / `EMAIL_APP_PASSWORD` — the account the notification is sent **from**.
  If you're using Gmail, you need an **App Password**, not your normal login password:
  1. Turn on 2-Step Verification on your Google account.
  2. Go to https://myaccount.google.com/apppasswords
  3. Generate a new app password and paste it into `EMAIL_APP_PASSWORD`.
  (Any other provider's SMTP works too — just change `SMTP_SERVER` / `SMTP_PORT`.)
- `TO_EMAIL` — where you want the alert sent (can be the same address).
- `TARGET_IG_USERNAME` / `TARGET_TT_USERNAME` — already set to `percyseries`, change if needed.

## 3. Test it

```bash
python monitor.py --once
```

This runs a single check. On the very first run it will just record whatever the
current latest post is (no email, since it has nothing to compare against yet).
Run it a second time to confirm it correctly detects "no new post."

## 4. Run it continuously

**Option A — leave it running:**
```bash
python monitor.py
```
This checks every `CHECK_INTERVAL_MINUTES` (default 15) and stays running until you stop it.

**Option B — cron (Mac/Linux), runs on a schedule without staying open:**
```bash
crontab -e
# add a line like this to check every 15 minutes:
*/15 * * * * cd /path/to/this/folder && /usr/bin/python3 monitor.py --once >> monitor.log 2>&1
```

**Option C — Windows Task Scheduler:** create a basic task that runs
`python.exe monitor.py --once` from this folder every 15 minutes.

## How it works

- **Instagram**: uses the `instaloader` library to read the account's public post list.
- **TikTok**: fetches the public profile page and parses the JSON TikTok embeds in the
  page itself (there's no public API for this), pulling out the newest video ID.
- Each check compares the latest post ID against the one saved in `state.json` from the
  last run. If it's different, you get an email and the new ID is saved.

## Hosting it remotely for free (GitHub Actions)

This runs the checker on GitHub's servers on a schedule, so nothing needs to stay on,
and it won't use your home IP. Public repos get **unlimited free** Actions minutes.

**1. Create a repo and push these files**

```bash
git init
git add .
git commit -m "Social media monitor"
```
Create a new repo on github.com (public — see note below), then:
```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

**2. Add your secrets**

In the repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these (same values as your local `.env`):

| Secret name | Example |
|---|---|
| `TARGET_IG_USERNAME` | `percyseries` |
| `TARGET_TT_USERNAME` | `percyseries` |
| `SMTP_SERVER` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `EMAIL_ADDRESS` | `youraddress@gmail.com` |
| `EMAIL_APP_PASSWORD` | your Gmail app password |
| `TO_EMAIL` | `youraddress@gmail.com` |
| `IG_LOGIN_USERNAME` | *(optional)* |
| `IG_LOGIN_PASSWORD` | *(optional)* |

Secrets are encrypted and masked in logs — this is true even on a public repo, so your
password is safe.

**3. That's it — it's live**

The workflow in `.github/workflows/monitor.yml` runs every 30 minutes automatically.
You can also trigger it by hand from the repo's **Actions** tab → *Social Media Monitor*
→ **Run workflow**, which is the easiest way to confirm it's working.

**Public vs. private repo:** Public repos get unlimited free Actions minutes, which is
why it's recommended here — nothing sensitive lives in the code or `state.json` (post
IDs only), your credentials stay in encrypted Secrets either way. If you'd rather keep
the repo private, that's fine too, just note the free tier there is 2,000 minutes/month;
at a 30-minute check interval you'll comfortably stay under that, but if you shorten
the interval a lot you may want to check your usage under **Settings → Billing**.

**Changing the schedule:** edit the `cron:` line in `.github/workflows/monitor.yml`.
Cron time is UTC. For example `*/15 * * * *` = every 15 minutes, `0 * * * *` = hourly.

## Other free hosting options

GitHub Actions is the most reliable free option for this and is what's set up here.
A few alternatives exist (Google Cloud Scheduler + Cloud Functions, PythonAnywhere
scheduled tasks, Render cron jobs), but their free-tier terms shift fairly often and
some restrict which outbound sites a free-tier task can reach, which would break the
scraping — worth checking their current pricing pages yourself if you want to compare.

## Things to know

- **Both platforms actively discourage automated scraping** and change their page
  structure periodically. Anonymous Instagram requests in particular get rate-limited
  fast — if Instagram checks start failing, either slow down `CHECK_INTERVAL_MINUTES`
  or set `IG_LOGIN_USERNAME` / `IG_LOGIN_PASSWORD` in `.env` (use a secondary account,
  not your main one — accounts used for scraping can occasionally get flagged).
- If TikTok checks start silently returning nothing, TikTok likely changed its page
  layout again — the `_extract_tiktok_json` / `_find_item_list` functions in
  `monitor.py` are the two places to update.
- For a private account (either platform), you'd need a logged-in session with access
  to that account — public scraping won't see anything.
