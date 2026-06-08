# yad2-watcher

[![CI](https://github.com/Jewgah/yad2-watcher/actions/workflows/ci.yml/badge.svg)](https://github.com/Jewgah/yad2-watcher/actions/workflows/ci.yml)

**[Live landing page →](https://yad2-watcher.web.app)**

Self-hosted watcher for [yad2.co.il](https://www.yad2.co.il). Build a search once,
and get an **instant Telegram ping for every new listing — each scored 0–10 by an
LLM** so you only look at the good ones. Works for **cars and rental apartments**
out of the box, and any other yad2 vertical you write an adapter for.

Python 3 standard library + `curl`. No frameworks, no database, no cloud.

```
🏠 🆕 Rental · 3-4 rooms · Hadera/Netanya

₪4,900/חודש | 3 חד׳ | 78 מ״ר | קומה 2
דירה — הרצל 14, חדרה
📍 מרכז העיר (אזור צפון השרון) | פרטי
🏷️ משופצת, מעלית, חניה
https://www.yad2.co.il/realestate/item/xxxxxxxx
⭐ 9/10 — Rent below the neighborhood rate, renovated, private seller
```

## How it works

yad2 fronts its pages with a Radware/ShieldSquare JS challenge. Setting the
`noscript=1` cookie makes yad2 serve a no-JS version whose `__NEXT_DATA__` script
tag embeds the full search feed as JSON. The watcher reads that, diffs listing
tokens against what it has already seen, fetches a little extra detail, asks an LLM
to score each new listing, and sends the keepers to Telegram.

```
fetch (noscript) → __NEXT_DATA__ → adapter.extract → token diff
                 → adapter.enrich → LLM score → gate → Telegram
```

## ⚠️ Read this first (legal / fair use)

This is a **personal-use automation tool that you run yourself, on your own
connection, against your own saved searches.** It is not a hosted service and it
does not redistribute yad2's data.

- yad2's Terms of Use restrict automated access. Running this is **your
  responsibility**; understand the terms before you do.
- Keep the polling interval gentle (the defaults are deliberately slow) and the
  request volume low. Don't hammer the site.
- Datacenter IPs get blocked immediately — this only works from a normal
  residential connection, which is also the point: it behaves like one person
  refreshing their own searches.
- No warranty. yad2 can change its markup or block the technique at any time.

If you're not comfortable with the above, don't run it.

## Setup

1. **Telegram bot** — message [@BotFather](https://t.me/BotFather) → `/newbot` →
   copy the token into `config.json` → `telegram.api_token`.
   (Tip: create a group, add the bot, and point `chat_id` at the group to share
   alerts with someone — a partner, a flatmate.)
2. **Link the chat** — send any message to your bot (or add it to your group),
   then:
   ```sh
   python3 watcher.py --setup-telegram
   ```
3. **AI rating (optional but recommended)** — set `rating.claude_bin` to your
   Claude CLI path (or adapt `rate_listing` to call any LLM / the Anthropic API).
   Set `rating.enabled` to `false` to skip scoring entirely.
4. **Schedule it** — copy `com.jordan.yad2watcher.plist` to
   `~/Library/LaunchAgents/`, fix the paths inside, then
   `launchctl load ~/Library/LaunchAgents/com.jordan.yad2watcher.plist`.
   (On Linux, a cron entry calling `python3 watcher.py` works the same way.)

> macOS note: launchd jobs can't read `~/Desktop`, `~/Documents`, or `~/Downloads`
> (TCC). Keep the project somewhere like `~/Projects`.

## Configuring searches

Each entry in `config.json` → `searches` is one watcher. See
`config.example.json`.

```jsonc
{
  "topic": "Outlander 7-seat petrol",
  "category": "cars",                 // which adapter: "cars" | "rentals"
  "url": "https://www.yad2.co.il/vehicles/cars?manufacturer=30&model=10381&...",
  "client_filters": { "engine_contains": "בנזין" },
  "disabled": false
}
```

- **`url`** — build the exact search on yad2 in your browser (model, year, price,
  km, region…) and paste it. The watcher reads page 1 only, so keep filters tight.
  Finding a model's IDs: search Google for `yad2.co.il vehicles cars <hebrew model
  name>` — every model has a canonical indexed URL with its `manufacturer`/`model`
  ids. Region uses `area=` ids (finer than `topArea=`).
- **`client_filters`** — applied on top of the URL against the parsed fields. Any
  `"<field>_contains": "value"` key keeps a listing only if `value` appears in that
  field (e.g. `engine_contains`, `property_contains`). Use for things the yad2 URL
  can't express. (Tip: cars expose a `seats=7` URL param — prefer it over a text
  filter; trim names don't always state seat count.)
- **`disabled: true`** — pause a watcher without deleting it.

First run of each watcher seeds state silently and sends a digest (count + cheapest
few). After that, only genuinely new listings notify.

## AI rating

Every notification can carry a `🤖 x/10 — reason` line. Two thresholds in
`config.rating`:

- `min_note_to_notify` — listings scored below this are logged and marked seen but
  **not sent** (fail-open: if the rater errors, the listing is sent anyway).
- `star_threshold` — scores at/above this get a `⭐` instead of `🤖`.

The scoring rubric is per-category (`rating_intro` in `adapters.py`) — cars weigh
km/maintenance/seller, rentals weigh ₪/m² vs the neighbourhood, floor, and
condition.

## Adding a new vertical

The engine is category-agnostic. To watch, say, second-hand goods, add one entry to
`ADAPTERS` in `adapters.py`:

```python
"products": {
    "emoji": "📦",
    "extract":     lambda it: {...},          # one feed entry -> normalized dict
    "item_url":    lambda token: f"https://www.yad2.co.il/products/item/{token}",
    "enrich":      None,                        # or a fn(item_page_data, listing)
    "format":      lambda l: "...",            # the Telegram body
    "rating_intro": lambda topic: "You are ...",
}
```

Then set `"category": "products"` on a search. No engine changes needed.

## Operations

```sh
python3 watcher.py --now         # run immediately (no jitter, ignore active hours)
python3 watcher.py --dry-run     # fetch + diff, but no Telegram and no state writes
tail -f data/watcher.log         # what each cycle did
```

State lives in `data/seen_<topic>.json` (tokens already notified). Delete a file to
re-seed that watcher. A `run.lock` prevents overlapping cycles. If yad2 blocks 5
cycles in a row you get a Telegram warning — usually fixed by waiting an hour or
opening yad2 once in your browser.

## License

MIT — see [LICENSE](LICENSE).
