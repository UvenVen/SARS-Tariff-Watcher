#!/usr/bin/env python3
"""
Website Watcher
----------------
Fetches a target page, extracts the main table (the SARS tariff amendments
table by default, but this works for any page with a comparable table/list
structure), diffs it against the previous run, and:
  - emails the user if new rows/entries were found
  - writes data/history.json (log of every check, used by the dashboard)
  - writes data/last_snapshot.json (the current state, for the next diff)

Designed to run daily via GitHub Actions (see .github/workflows/check.yml)
but works fine run locally too: `python check_site.py`
"""

import os
import sys
import json
import hashlib
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Config (env vars are set via GitHub Actions secrets / workflow file)
# ---------------------------------------------------------------------------
TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://www.sars.gov.za/legal-counsel/secondary-legislation/tariff-amendments/tariff-amendments-2026/",
)
EMAIL_TO = os.environ.get("EMAIL_TO", "uven@easyclear.co.za")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)
WHATSAPP_PHONE = os.environ.get("WHATSAPP_PHONE", "")
WHATSAPP_APIKEY = os.environ.get("WHATSAPP_APIKEY", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")  # auto-set by GitHub Actions, e.g. "UvenVen/SARS-Tariff-Watcher"
SCREENSHOT_PUBLIC_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/data/latest_screenshot.png"
    if GITHUB_REPOSITORY else ""
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "last_snapshot.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
SCREENSHOT_PATH = os.path.join(DATA_DIR, "latest_screenshot.png")
MAX_HISTORY_ENTRIES = 200

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Fetch + extract
# ---------------------------------------------------------------------------
def fetch_page(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_rows(html: str) -> list[str]:
    """
    Pull the main content table off the page and return each row as a
    normalised text string. Picks the table with the most rows on the page,
    which in practice is the actual data table (nav/footer tables, if any,
    are much smaller).
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    if not tables:
        # Fallback: no table found, treat list items in the main content
        # area as "rows" instead, so the script still degrades gracefully.
        main = soup.find("main") or soup
        items = main.find_all("li")
        return [normalise(li.get_text(" ", strip=True)) for li in items if li.get_text(strip=True)]

    target_table = max(tables, key=lambda t: len(t.find_all("tr")))
    rows = []
    for tr in target_table.find_all("tr"):
        text = normalise(tr.get_text(" ", strip=True))
        if text:
            rows.append(text)
    return rows


def normalise(text: str) -> str:
    return " ".join(text.split())


def row_hash(row: str) -> str:
    return hashlib.sha256(row.encode("utf-8")).hexdigest()


def take_screenshot(url: str, out_path: str):
    """Screenshot of the visible top portion of the target page (not the full scrolled page)."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.screenshot(path=out_path, full_page=False)
            browser.close()
        print(f"Screenshot saved to {out_path}")
        return True
    except Exception as e:
        print(f"Screenshot failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------
def diff_rows(old_rows: list[str], new_rows: list[str]) -> dict:
    old_set = {row_hash(r): r for r in old_rows}
    new_set = {row_hash(r): r for r in new_rows}

    added = [new_set[h] for h in new_set if h not in old_set]
    removed = [old_set[h] for h in old_set if h not in new_set]

    return {"added": added, "removed": removed}


def send_whatsapp(message: str):
    if not (WHATSAPP_PHONE and WHATSAPP_APIKEY):
        print("WhatsApp not configured (missing env vars) - skipping.")
        return
    try:
        resp = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": WHATSAPP_PHONE, "text": message[:1000], "apikey": WHATSAPP_APIKEY},
            timeout=20,
        )
        print(f"WhatsApp send status: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        print(f"WhatsApp send failed: {e}")


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def send_email(subject: str, body_text: str, body_html: str | None = None, attachment_path: str | None = None):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and EMAIL_TO):
        print("SMTP not configured (missing env vars) - skipping email send.")
        print("---- Would have sent ----")
        print("Subject:", subject)
        print(body_text)
        print("--------------------------")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            img = MIMEImage(f.read(), name=os.path.basename(attachment_path))
        msg.attach(img)

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=context)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
    print(f"Email sent to {EMAIL_TO}")


def build_email_body(added: list[str], removed: list[str], row_count: int, changed: bool) -> tuple[str, str]:
    if changed:
        lines = [f"Changes detected on:\n{TARGET_URL}\n"]
        if added:
            lines.append(f"\n🆕 {len(added)} new row(s):\n")
            for r in added:
                lines.append(f"  - {r[:400]}")
        if removed:
            lines.append(f"\n❌ {len(removed)} row(s) removed:\n")
            for r in removed:
                lines.append(f"  - {r[:400]}")
    else:
        lines = [
            f"Daily check complete — no changes.\n",
            f"Page: {TARGET_URL}",
            f"Rows on page: {row_count}",
        ]
    text = "\n".join(lines)

    if changed:
        html_rows_added = "".join(f"<li style='margin-bottom:8px'>{r}</li>" for r in added)
        html_rows_removed = "".join(f"<li style='margin-bottom:8px'>{r}</li>" for r in removed)
        html = f"""
        <html><body style="font-family:sans-serif;">
        <p>Changes detected on:<br><a href="{TARGET_URL}">{TARGET_URL}</a></p>
        {f"<h3>🆕 New rows ({len(added)})</h3><ul>{html_rows_added}</ul>" if added else ""}
        {f"<h3>❌ Removed rows ({len(removed)})</h3><ul>{html_rows_removed}</ul>" if removed else ""}
        </body></html>
        """
    else:
        html = f"""
        <html><body style="font-family:sans-serif;">
        <p>✅ Daily check complete — no changes.</p>
        <p>Page: <a href="{TARGET_URL}">{TARGET_URL}</a><br>
        Rows on page: {row_count}</p>
        </body></html>
        """
    return text, html


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def append_history(entry: dict):
    history = load_json(HISTORY_PATH, [])
    history.insert(0, entry)
    history = history[:MAX_HISTORY_ENTRIES]
    save_json(HISTORY_PATH, history)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking {TARGET_URL}")

    try:
        html = fetch_page(TARGET_URL)
        new_rows = extract_rows(html)
    except Exception as e:
        print(f"ERROR fetching/parsing page: {e}")
        append_history({
            "timestamp": now,
            "status": "error",
            "message": str(e),
            "added_count": 0,
            "removed_count": 0,
        })
        sys.exit(1)

    if not new_rows:
        print("WARNING: no rows extracted - page structure may have changed.")

    screenshot_ok = take_screenshot(TARGET_URL, SCREENSHOT_PATH)
    screenshot_for_email = SCREENSHOT_PATH if screenshot_ok else None

    snapshot = load_json(SNAPSHOT_PATH, {"rows": []})
    old_rows = snapshot.get("rows", [])

    is_first_run = len(old_rows) == 0
    diff = diff_rows(old_rows, new_rows)

    changed = bool(diff["added"] or diff["removed"])

    if is_first_run:
        print(f"First run - baseline captured ({len(new_rows)} rows). No email sent.")
        status = "baseline"
    elif changed:
        print(f"CHANGE DETECTED: +{len(diff['added'])} / -{len(diff['removed'])}")
        subject = f"🔔 Update on SARS Tariff Amendments 2026 page ({len(diff['added'])} new)"
        text, html_body = build_email_body(diff["added"], diff["removed"], len(new_rows), changed=True)
        send_email(subject, text, html_body, attachment_path=screenshot_for_email)
        wa_lines = [f"🔔 SARS Tariff Amendments: {len(diff['added'])} new notice(s)"]
        for r in diff["added"][:5]:
            wa_lines.append(f"- {r[:150]}")
        wa_lines.append(TARGET_URL)
        if screenshot_ok and SCREENSHOT_PUBLIC_URL:
            wa_lines.append(f"📸 {SCREENSHOT_PUBLIC_URL}")
        send_whatsapp("\n".join(wa_lines))
        status = "changed"
    else:
        print("No changes.")
        subject = "✅ Daily check: no changes — SARS Tariff Amendments 2026"
        text, html_body = build_email_body([], [], len(new_rows), changed=False)
        send_email(subject, text, html_body, attachment_path=screenshot_for_email)
        wa_no_change = f"✅ SARS Tariff Amendments: no changes ({len(new_rows)} rows checked)"
        if screenshot_ok and SCREENSHOT_PUBLIC_URL:
            wa_no_change += f"\n📸 {SCREENSHOT_PUBLIC_URL}"
        send_whatsapp(wa_no_change)
        status = "unchanged"

    # persist new snapshot
    save_json(SNAPSHOT_PATH, {"rows": new_rows, "checked_at": now})

    append_history({
        "timestamp": now,
        "status": status,
        "added_count": len(diff["added"]),
        "removed_count": len(diff["removed"]),
        "added_preview": [r[:200] for r in diff["added"][:5]],
        "row_count": len(new_rows),
    })

    print("Done.")


if __name__ == "__main__":
    main()
