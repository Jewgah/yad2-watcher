#!/usr/bin/env python3
"""
yad2-watcher — polls yad2.co.il searches and notifies new listings via Telegram,
each scored 0-10 by an LLM. Category-agnostic: cars, rental apartments, or any
yad2 vertical you write an adapter for (see adapters.py).

Bypasses the Radware/ShieldSquare JS challenge with the `noscript=1` cookie trick
(yad2 serves a no-JS page whose __NEXT_DATA__ embeds the full feed JSON).

Self-hosted, personal-use tool. You run it on your own connection against your own
saved searches. Respect yad2's Terms of Use and keep the polling interval gentle.

Usage:
  python3 watcher.py                  # normal run (launchd): jitter + active-hours guard
  python3 watcher.py --now            # run immediately, no jitter, ignore active hours
  python3 watcher.py --dry-run        # fetch + diff but don't notify / don't save state
  python3 watcher.py --setup-telegram # capture chat_id after you message the bot
"""

import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime

from adapters import get_adapter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
COOKIE_JAR = os.path.join(DATA_DIR, "cookies.txt")
LOG_PATH = os.path.join(DATA_DIR, "watcher.log")
LOCK_PATH = os.path.join(DATA_DIR, "run.lock")
LOCK_MAX_AGE = 1500  # seconds; older locks are considered stale (crashed run)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.1 Safari/605.1.15"
)
CAPTCHA_ALERT_THRESHOLD = 5
# Feed buckets that are recommendations, not results of the user's search —
# excluded so a sparse search doesn't notify similar-but-unfiltered listings.
IGNORE_FEED_KEYS = {"lookalike"}


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def slugify(topic):
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")


def state_path(topic):
    return os.path.join(DATA_DIR, f"seen_{slugify(topic)}.json")


def load_state(topic):
    path = state_path(topic)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"tokens": [], "captcha_streak": 0}


def save_state(topic, state):
    with open(state_path(topic), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def fetch_page(url):
    """Fetch a yad2 search page with the noscript cookie trick. Returns HTML or None."""
    cmd = [
        "curl", "-s", "-L", "--max-time", "30", "--compressed",
        "-A", USER_AGENT,
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: he-IL,he;q=0.9,en;q=0.8",
        "-c", COOKIE_JAR, "-b", COOKIE_JAR, "-b", "noscript=1",
        url,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=45)
    except subprocess.TimeoutExpired:
        return None
    if res.returncode != 0:
        return None
    return res.stdout.decode("utf-8", errors="replace")


def is_captcha(html):
    return "ShieldSquare" in html[:20000] or "__NEXT_DATA__" not in html


def extract_next_data(html):
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def parse_listings(html, adapter):
    """Extract deduped listing dicts from __NEXT_DATA__ via the category adapter.

    yad2 feeds split listings across category-specific sections (cars: platinum /
    boost / solo / commercial / private; rentals: private / agency / yad1 / ...).
    Rather than hardcode names, we take every list-of-objects-with-a-token in the
    feed dict — robust across verticals and future section renames."""
    data = extract_next_data(html)
    if data is None:
        return None
    queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    feed = None
    for q in queries:
        d = q.get("state", {}).get("data")
        if isinstance(d, dict) and "private" in d and "pagination" in d:
            feed = d
            break
    if feed is None:
        return None
    listings, seen = [], set()
    for key, value in feed.items():
        if key in IGNORE_FEED_KEYS or not isinstance(value, list):
            continue
        for it in value:
            if not isinstance(it, dict):
                continue
            token = it.get("token")
            if not token or token in seen:
                continue
            seen.add(token)
            listings.append(adapter["extract"](it))
    return listings


def enrich_listing(l, spacing, adapter):
    """Fetch the listing's own page for extra detail (cars: km/test/seller).
    Adapters whose feed is already detailed (rentals) set enrich=None and skip the
    fetch entirely. Best-effort: on any failure the basic listing is returned."""
    if not adapter.get("enrich"):
        return l
    time.sleep(random.uniform(*spacing))  # don't burst right after the search fetch
    html = fetch_page(adapter["item_url"](l["token"]))
    if html is None or is_captcha(html):
        return l
    data = extract_next_data(html)
    if data is None:
        return l
    return adapter["enrich"](data, l)


def passes_filters(listing, filters):
    """Generic substring gate: a `<field>_contains` filter keeps a listing only
    when the value appears in str(listing[field]). Works for any adapter field."""
    if not filters:
        return True
    for key, needle in filters.items():
        if not key.endswith("_contains"):
            continue
        field = key[: -len("_contains")]
        if needle not in str(listing.get(field, "")):
            return False
    return True


def rate_listing(config, topic, l, adapter):
    """Score the offer 0-10 via the claude CLI (subscription). Best-effort: None on any failure."""
    cfg = config.get("rating") or {}
    if not cfg.get("enabled"):
        return None
    claude_bin = cfg.get("claude_bin", "")
    if not os.path.exists(claude_bin):
        return None
    facts = {k: v for k, v in l.items() if k != "token" and v not in (None, "", [])}
    prompt = (
        adapter["rating_intro"](topic) + "\n"
        f"Listing: {json.dumps(facts, ensure_ascii=False)}\n"
        "Reply EXACTLY on two lines, in English:\n"
        "SCORE: <x>/10\n"
        "REASON: <12 words MAX, terse>"
    )
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # force subscription auth (cf. zshrc alias)
    try:
        res = subprocess.run(
            [claude_bin, "-p", prompt], capture_output=True, timeout=180, env=env
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = res.stdout.decode("utf-8", errors="replace")
    m = re.search(r"(?:SCORE|NOTE):\s*(\d+(?:[.,]\d)?)\s*/\s*10", out)
    if not m:
        log(f"[rating] unparseable claude output: {out[:120]!r}")
        return None
    score = float(m.group(1).replace(",", "."))
    r = re.search(r"(?:REASON|RAISON):\s*(.+)", out)
    reason = r.group(1).strip() if r else ""
    star = cfg.get("star_threshold")
    emoji = "⭐" if (star is not None and score >= star) else "🤖"
    note = f"{emoji} {m.group(1)}/10 — {reason}" if reason else f"{emoji} {m.group(1)}/10"
    return score, note


def render_listing(config, topic, l, adapter):
    """Returns (text, score). score is None when rating is disabled/failed."""
    text = adapter["format"](l)
    rated = rate_listing(config, topic, l, adapter)
    if rated:
        score, note = rated
        return f"{text}\n{note}", score
    return text, None


def below_threshold(config, score):
    """True when the score exists and sits under min_note_to_notify (fail-open)."""
    threshold = (config.get("rating") or {}).get("min_note_to_notify")
    return threshold is not None and score is not None and score < threshold


def send_telegram(config, text, dry_run=False):
    """Returns False only on an actual send failure (so the caller can retry next cycle).
    Skipped sends (dry-run / telegram not configured yet) count as success — that way
    the state still seeds silently before the bot is wired up."""
    tg = config.get("telegram", {})
    token, chat_id = tg.get("api_token", ""), tg.get("chat_id", "")
    if dry_run or not token or "PASTE" in token or not chat_id:
        log(f"[telegram skipped] {text[:120]}...")
        return True
    res = subprocess.run(
        [
            "curl", "-s", "--max-time", "20",
            f"https://api.telegram.org/bot{token}/sendMessage",
            "-d", f"chat_id={chat_id}",
            "--data-urlencode", f"text={text}",
            "-d", "disable_web_page_preview=true",
        ],
        capture_output=True,
    )
    try:
        ok = json.loads(res.stdout.decode() or "{}").get("ok", False)
    except json.JSONDecodeError:
        ok = False
    if not ok:
        log(f"[telegram FAILED] {res.stdout.decode(errors='replace')[:200]}")
    return ok


def setup_telegram():
    """After the user sends any message to the bot, capture the chat_id into config."""
    config = load_config()
    token = config.get("telegram", {}).get("api_token", "")
    if not token or "PASTE" in token:
        print("Set telegram.api_token in config.json first (get it from @BotFather).")
        sys.exit(1)
    res = subprocess.run(
        ["curl", "-s", f"https://api.telegram.org/bot{token}/getUpdates"],
        capture_output=True,
    )
    try:
        updates = json.loads(res.stdout.decode() or "{}")
    except json.JSONDecodeError:
        print("Telegram API unreachable (no/invalid response). Check network and re-run.")
        sys.exit(1)
    if not updates.get("ok"):
        print(f"Telegram rejected the token: {updates.get('description', 'no response')}")
        sys.exit(1)
    chats = {}
    for u in updates.get("result", []):
        # groups appear via my_chat_member (bot added) as well as plain messages
        for key in ("message", "my_chat_member"):
            if key in u:
                chat = u[key]["chat"]
                chats[str(chat["id"])] = chat.get("title") or chat.get("first_name", "?")
    if not chats:
        print("No messages found. Open Telegram, send any message to your bot, then re-run.")
        sys.exit(1)
    chat_id = list(chats.keys())[-1]
    config["telegram"]["chat_id"] = chat_id
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"chat_id={chat_id} ({chats[chat_id]}) saved to config.json")
    send_telegram(config, "✅ yad2-watcher connected. You'll get new listings here.")


def acquire_lock():
    if os.path.exists(LOCK_PATH):
        if time.time() - os.path.getmtime(LOCK_PATH) < LOCK_MAX_AGE:
            return False
    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


def run(dry_run=False):
    config = load_config()
    searches = [s for s in config.get("searches", []) if not s.get("disabled")]
    if not searches:
        log("no enabled searches in config.json")
        return
    if not acquire_lock():
        log("another run is in progress (run.lock fresh) — skipping this cycle")
        return
    try:
        _run(config, searches, dry_run)
    finally:
        release_lock()


def _run(config, searches, dry_run):
    spacing = config.get("request_spacing_seconds", [20, 40])
    for i, search in enumerate(searches):
        if i > 0:
            time.sleep(random.uniform(*spacing))
        topic, url = search["topic"], search["url"]
        adapter = get_adapter(search.get("category"))
        state = load_state(topic)
        html = fetch_page(url)
        if html is None or is_captcha(html):
            state["captcha_streak"] = state.get("captcha_streak", 0) + 1
            log(f"[{topic}] captcha/blocked (streak {state['captcha_streak']})")
            if state["captcha_streak"] == CAPTCHA_ALERT_THRESHOLD:
                send_telegram(
                    config,
                    f"⚠️ yad2-watcher: \"{topic}\" blocked by captcha "
                    f"{CAPTCHA_ALERT_THRESHOLD} times in a row. Worth a look.",
                    dry_run,
                )
            if not dry_run:
                save_state(topic, state)
            continue
        listings = parse_listings(html, adapter)
        if listings is None:
            log(f"[{topic}] page OK but feed not found — yad2 markup may have changed")
            continue
        state["captcha_streak"] = 0
        matching = [l for l in listings if passes_filters(l, search.get("client_filters"))]
        first_run = not state.get("seeded")
        new = [l for l in matching if l["token"] not in state["tokens"]]
        log(f"[{topic}] {len(matching)} matching, {len(new)} new{' (first run)' if first_run else ''}")
        emoji = adapter["emoji"]
        notified = set()
        if first_run:
            top = sorted(matching, key=lambda x: x.get("price") or 9e9)[:5]
            top = [enrich_listing(l, spacing, adapter) for l in top]
            rendered = [render_listing(config, topic, l, adapter) for l in top]
            kept = [text for text, score in rendered if not below_threshold(config, score)]
            hidden = len(rendered) - len(kept)
            header = f"{emoji} Watcher \"{topic}\" started — {len(matching)} current listings."
            if hidden:
                threshold = config["rating"]["min_note_to_notify"]
                header += f" ({hidden} scored <{threshold}/10, hidden)"
            digest = "\n\n".join(kept)
            send_telegram(
                config,
                header + (f"\nTop by price:\n\n{digest}" if digest else ""),
                dry_run,
            )
            state["seeded"] = True
            notified = {l["token"] for l in new}
        else:
            for l in new:
                l = enrich_listing(l, spacing, adapter)
                text, score = render_listing(config, topic, l, adapter)
                if below_threshold(config, score):
                    log(f"[{topic}] {l['token']} scored {score}/10 — below threshold, not sent")
                    notified.add(l["token"])  # seen: don't re-rate every cycle
                    continue
                # only mark seen if the send didn't hard-fail, so it retries next cycle
                if send_telegram(config, f"{emoji} 🆕 {topic}\n\n{text}", dry_run):
                    notified.add(l["token"])
        state["tokens"] = sorted(set(state["tokens"]) | notified)
        if not dry_run:
            save_state(topic, state)


def install_schedule():
    """Generate + load a launchd agent (macOS) that runs the watcher every
    `poll_interval_minutes` from config. On other platforms, print a cron line."""
    config = load_config()
    minutes = int(config.get("poll_interval_minutes", 30))
    interval = max(60, minutes * 60)
    active = config.get("active_hours", [8, 22])
    if sys.platform != "darwin":
        every = minutes if 1 <= minutes < 60 else 1
        print(f"Non-macOS — add this cron line (every {minutes} min; the active-hours "
              f"guard {active} still applies in-script):")
        print(f"  */{every} * * * * cd {BASE_DIR} && {sys.executable} watcher.py")
        return
    label = "com.yad2watcher"
    path = os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f'  <key>Label</key><string>{label}</string>\n'
        '  <key>ProgramArguments</key>\n'
        f'  <array><string>{sys.executable}</string>'
        f'<string>{os.path.join(BASE_DIR, "watcher.py")}</string></array>\n'
        f'  <key>WorkingDirectory</key><string>{BASE_DIR}</string>\n'
        f'  <key>StartInterval</key><integer>{interval}</integer>\n'
        '  <key>RunAtLoad</key><true/>\n'
        f'  <key>StandardOutPath</key><string>{os.path.join(DATA_DIR, "launchd.log")}</string>\n'
        f'  <key>StandardErrorPath</key><string>{os.path.join(DATA_DIR, "launchd.log")}</string>\n'
        '</dict></plist>\n'
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(plist)
    subprocess.run(["launchctl", "unload", path], capture_output=True)
    res = subprocess.run(["launchctl", "load", "-w", path], capture_output=True)
    if res.returncode == 0:
        print(f"✅ Scheduled: every {minutes} min, active hours {active}.")
        print(f"   agent: {path}")
        print("   change cadence: edit poll_interval_minutes in config.json, rerun --install-schedule")
    else:
        print(f"⚠️ launchctl load failed: {res.stderr.decode(errors='replace')[:200]}")
        print(f"   plist written to {path}; load manually: launchctl load -w {path}")


def uninstall_schedule():
    """Stop and remove the launchd agent (macOS)."""
    path = os.path.expanduser("~/Library/LaunchAgents/com.yad2watcher.plist")
    subprocess.run(["launchctl", "unload", path], capture_output=True)
    try:
        os.remove(path)
        print(f"Removed schedule ({path}).")
    except OSError:
        print("No schedule installed (nothing to remove).")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    args = sys.argv[1:]
    if "--setup-telegram" in args:
        setup_telegram()
        return
    if "--install-schedule" in args:
        install_schedule()
        return
    if "--uninstall-schedule" in args:
        uninstall_schedule()
        return
    dry_run = "--dry-run" in args
    now = "--now" in args or dry_run
    if not now:
        config = load_config()
        start_h, end_h = config.get("active_hours", [8, 22])
        h = datetime.now().hour
        if not (start_h <= h < end_h):
            return  # quiet outside active hours
        time.sleep(random.uniform(0, 90))  # jitter so polls don't look mechanical
    run(dry_run=dry_run)


if __name__ == "__main__":
    main()
