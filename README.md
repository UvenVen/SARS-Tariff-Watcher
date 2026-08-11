# Tariff Amendments Watcher

Checks the SARS Tariff Amendments 2026 page daily, emails you when a new
notice is added, and keeps a dashboard log of every check.

Runs entirely on GitHub's free tier (Actions + Pages) — nothing needs to
stay on your PC.

**Target page:** https://www.sars.gov.za/legal-counsel/secondary-legislation/tariff-amendments/tariff-amendments-2026/

---

## 1. Create the repo

1. Go to https://github.com/new
2. Name it something like `sars-tariff-watcher`
3. Set it to **Public** (needed for free GitHub Pages on a free account —
   your data is just page-check logs, nothing sensitive)
4. Don't initialise with a README (we already have one)

Upload all the files in this folder to that repo — easiest way is via the
GitHub web UI: "Add file" → "Upload files", drag the whole folder in,
commit.

## 2. Set your email sending details

You need SMTP credentials for `uven@easyclear.co.za` (or whatever inbox
sends the alert). Go to your repo → **Settings → Secrets and variables →
Actions**.

Under **Secrets**, add:

| Name | Value |
|---|---|
| `SMTP_HOST` | your mail provider's SMTP server (see below) |
| `SMTP_PORT` | usually `587` |
| `SMTP_USER` | the login email address (e.g. `uven@easyclear.co.za`) |
| `SMTP_PASS` | an **app password** (not your normal login password — see below) |
| `EMAIL_FROM` | same as `SMTP_USER`, or a "from" address your provider allows |

Under **Variables** (same page, different tab), add:

| Name | Value |
|---|---|
| `TARGET_URL` | `https://www.sars.gov.za/legal-counsel/secondary-legislation/tariff-amendments/tariff-amendments-2026/` |
| `EMAIL_TO` | `uven@easyclear.co.za` |

### Finding your SMTP details

**If easyclear.co.za mail runs on Microsoft 365 / Outlook:**
- `SMTP_HOST` = `smtp.office365.com`
- `SMTP_PORT` = `587`
- You'll need an **app password** — if your org has MFA on, generate one at
  https://mysignins.microsoft.com/security-info (Add method → App password).
  If that option isn't there, your admin may have it disabled — worth
  asking IT/whoever manages the domain, or use a Gmail account instead
  (see below) and just set `EMAIL_FROM` to that Gmail address.

**If it runs on Google Workspace:**
- `SMTP_HOST` = `smtp.gmail.com`
- `SMTP_PORT` = `587`
- Generate an app password at https://myaccount.google.com/apppasswords
  (needs 2-Step Verification turned on first)

**Not sure which one you're on?** Check what login page you use for
webmail — outlook.office.com means Microsoft 365, mail.google.com means
Google Workspace.

**Simplest fallback:** if getting SMTP access to the business inbox is a
hassle, create a free Gmail account just for sending these alerts (e.g.
`sars.watcher.alerts@gmail.com`), generate an app password for it, and
keep `EMAIL_TO` as `uven@easyclear.co.za`. The alert will just arrive
*from* the Gmail address instead of from your own domain.

## 3. Turn on GitHub Pages (for the dashboard)

Repo → **Settings → Pages** → under "Build and deployment", set
**Source: Deploy from a branch**, branch `main`, folder `/ (root)` → Save.

Your dashboard will be live at:
`https://<your-github-username>.github.io/<repo-name>/`

(takes a minute or two to go live after saving)

## 4. Run it for the first time

Repo → **Actions** tab → click "Check Website Daily" in the left sidebar →
**Run workflow** button → Run workflow.

This first run just captures a baseline (no email — nothing to compare
against yet). After that, it runs automatically every day at 08:00 SAST
and will only email you when something actually changes.

You can change the schedule by editing the `cron` line in
`.github/workflows/check.yml` — it's currently `0 6 * * *` (06:00 UTC).

## How it works

- `check_site.py` fetches the page, finds the main table, and compares
  each row against the previous run (stored in `data/last_snapshot.json`)
- New rows → email sent + logged in `data/history.json`
- Every run (change or not) gets logged, so the dashboard always shows
  when it last checked
- `index.html` is the dashboard — reads `data/history.json` straight from
  the repo, no backend needed

## Testing locally (optional)

```bash
pip install -r requirements.txt
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=you@gmail.com SMTP_PASS=xxxx EMAIL_TO=uven@easyclear.co.za
python check_site.py
```

If SMTP env vars aren't set, it just prints what it *would* have emailed
instead of failing.
