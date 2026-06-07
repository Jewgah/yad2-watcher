#!/usr/bin/env python3
"""
yad2-watcher — polls yad2.co.il vehicle searches and notifies new listings via Telegram.

Bypasses the Radware/ShieldSquare JS challenge with the `noscript=1` cookie trick
(yad2 serves a no-JS page whose __NEXT_DATA__ embeds the full feed JSON).

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
COOKIE_JAR = os.path.join(DATA_DIR, "cookies.txt")
LOG_PATH = os.path.join(DATA_DIR, "watcher.log")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.1 Safari/605.1.15"
)
FEED_SECTIONS = ("platinum", "boost", "solo", "commercial", "private")
CAPTCHA_ALERT_THRESHOLD = 5


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


def parse_listings(html):
    """Extract deduped listing dicts from __NEXT_DATA__."""
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S
    )
    if not m:
        return None
    data = json.loads(m.group(1))
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
    for section in FEED_SECTIONS:
        for it in feed.get(section) or []:
            token = it.get("token")
            if not token or token in seen:
                continue
            seen.add(token)
            listings.append({
                "token": token,
                "price": it.get("price"),
                "year": (it.get("vehicleDates") or {}).get("yearOfProduction"),
                "hand": (it.get("hand") or {}).get("text", "?"),
                "km": it.get("km"),
                "engine": (it.get("engineType") or {}).get("text", "?"),
                "submodel": (it.get("subModel") or {}).get("text", ""),
                "model": "{} {}".format(
                    (it.get("manufacturer") or {}).get("text", ""),
                    (it.get("model") or {}).get("text", ""),
                ).strip(),
                "area": ((it.get("address") or {}).get("area") or {}).get("text", "?"),
                "created": it.get("createdAt", ""),
                "url": f"https://www.yad2.co.il/vehicles/item/{token}",
            })
    return listings


def passes_filters(listing, filters):
    if not filters:
        return True
    if "engine_contains" in filters and filters["engine_contains"] not in listing["engine"]:
        return False
    if "submodel_contains" in filters and filters["submodel_contains"] not in listing["submodel"]:
        return False
    return True


def format_listing(l):
    km = f"{l['km']:,} km" if isinstance(l.get("km"), int) else "km ?"
    price = f"₪{l['price']:,}" if isinstance(l.get("price"), int) else "₪?"
    return (
        f"{price} | {l['year']} | {l['hand']} | {km}\n"
        f"{l['model']} — {l['submodel']}\n"
        f"📍 {l['area']} | מנוע: {l['engine']}\n"
        f"{l['url']}"
    )


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
    chats = {
        str(u["message"]["chat"]["id"]): u["message"]["chat"].get(
            "first_name", u["message"]["chat"].get("title", "?")
        )
        for u in updates.get("result", [])
        if "message" in u
    }
    if not chats:
        print("No messages found. Open Telegram, send any message to your bot, then re-run.")
        sys.exit(1)
    chat_id = list(chats.keys())[-1]
    config["telegram"]["chat_id"] = chat_id
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"chat_id={chat_id} ({chats[chat_id]}) saved to config.json")
    send_telegram(config, "✅ yad2-watcher connecté. Tu recevras les nouvelles annonces ici.")


def run(dry_run=False):
    config = load_config()
    searches = [s for s in config.get("searches", []) if not s.get("disabled")]
    if not searches:
        log("no enabled searches in config.json")
        return
    spacing = config.get("request_spacing_seconds", [20, 40])
    for i, search in enumerate(searches):
        if i > 0:
            time.sleep(random.uniform(*spacing))
        topic, url = search["topic"], search["url"]
        state = load_state(topic)
        html = fetch_page(url)
        if html is None or is_captcha(html):
            state["captcha_streak"] = state.get("captcha_streak", 0) + 1
            log(f"[{topic}] captcha/blocked (streak {state['captcha_streak']})")
            if state["captcha_streak"] == CAPTCHA_ALERT_THRESHOLD:
                send_telegram(
                    config,
                    f"⚠️ yad2-watcher: « {topic} » bloqué par captcha "
                    f"{CAPTCHA_ALERT_THRESHOLD} fois de suite. À vérifier.",
                    dry_run,
                )
            if not dry_run:
                save_state(topic, state)
            continue
        listings = parse_listings(html)
        if listings is None:
            log(f"[{topic}] page OK but feed not found — yad2 markup may have changed")
            continue
        state["captcha_streak"] = 0
        matching = [l for l in listings if passes_filters(l, search.get("client_filters"))]
        first_run = not state.get("seeded")
        new = [l for l in matching if l["token"] not in state["tokens"]]
        log(f"[{topic}] {len(matching)} matching, {len(new)} new{' (first run)' if first_run else ''}")
        notified = set()
        if first_run:
            digest = "\n\n".join(
                format_listing(l)
                for l in sorted(matching, key=lambda x: x.get("price") or 9e9)[:5]
            )
            send_telegram(
                config,
                f"🚗 Watcher « {topic} » démarré — {len(matching)} annonces actuelles."
                + (f"\nTop 5 par prix :\n\n{digest}" if digest else ""),
                dry_run,
            )
            state["seeded"] = True
            notified = {l["token"] for l in new}
        else:
            for l in new:
                # only mark seen if the send didn't hard-fail, so it retries next cycle
                if send_telegram(config, f"🆕 {topic}\n\n{format_listing(l)}", dry_run):
                    notified.add(l["token"])
        state["tokens"] = sorted(set(state["tokens"]) | notified)
        if not dry_run:
            save_state(topic, state)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    args = sys.argv[1:]
    if "--setup-telegram" in args:
        setup_telegram()
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
