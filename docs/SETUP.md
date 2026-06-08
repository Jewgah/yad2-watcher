# Setup guide

Zero to AI deal-alerts in about 10 minutes. Hand-held; no prior experience needed.

## 0. Prerequisites

- **macOS or Linux**, **Python 3** (`python3 --version`), and **curl** (preinstalled on both).
- A **Telegram** account.
- *(Optional, for AI scoring)* **Claude Code** installed (`claude`), or any LLM you wire
  into `rate_listing`. You can also run with scoring off.

## 1. Get the code

```sh
git clone https://github.com/Jewgah/yad2-watcher
cd yad2-watcher
cp config.example.json config.json     # your private settings (gitignored)
```

> **macOS:** keep the folder **outside** `~/Desktop`, `~/Documents`, and `~/Downloads`.
> macOS blocks background jobs (launchd) from reading those (TCC). `~/Projects` is a good home.

## 2. Create a Telegram bot

1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot`. Choose a display name, then a username ending in `bot`.
3. BotFather replies with a **token** like `123456789:AAH...`. Copy it.
4. Paste it into `config.json` → `telegram.api_token`.

## 3. Link your chat

- **Just you:** open your new bot and send it any message (e.g. "hi").
- **Shared (you + a partner):** create a Telegram **group**, add the bot, send a message in it.

Then capture the chat id:

```sh
python3 watcher.py --setup-telegram
```

It writes `telegram.chat_id` into `config.json` and sends a "✅ connected" message to confirm.

## 4. (Optional) AI scoring

In `config.json` → `rating`:

- Set `claude_bin` to your Claude CLI path (`which claude`), **or** set `enabled` to `false`
  to skip scoring entirely.
- `min_note_to_notify` — hide listings scored below this (e.g. `7`).
- `star_threshold` — score ≥ this gets a ⭐ instead of 🤖 (e.g. `8`).

Scoring is **fail-open**: if the rater errors, the listing is sent anyway.

## 5. Add a search

**Option A — by hand.** Build the search on yad2.co.il in your browser (model, price,
area, rooms…), copy the resulting URL, and paste it into `config.json` → `searches[].url`.

**Option B — let AI build it.** Copy the bundled skill into Claude Code and describe what
you want in plain language:

```sh
cp -r skills/yad2-search ~/.claude/skills/
```
```
/yad2-search reliable 7-seat petrol SUV under ₪80k near Netanya, 2015+
```

It looks up the **real** yad2 ids (no guessing) and writes the entry for you.

> Need a filter the URL can't express (e.g. petrol only)? Use `client_filters`, e.g.
> `"client_filters": { "engine_contains": "בנזין" }`. See the main README.

## 6. First run

```sh
python3 watcher.py --now      # run now, ignore active-hours, no jitter
```

The first run of each search **seeds silently** and sends a digest (count + cheapest few).
After that, only genuinely new listings notify.

## 7. Run it on a schedule

Set how often it checks, in `config.json`:

```json
"poll_interval_minutes": 30
```

Then install the scheduler:

```sh
python3 watcher.py --install-schedule
```

- **macOS:** generates and loads a launchd agent for you. Rerun after changing the interval;
  `python3 watcher.py --uninstall-schedule` stops it.
- **Linux:** it prints the cron line to add.

`active_hours` (e.g. `[8, 22]`) keeps it quiet outside those hours.

## Troubleshooting

| Symptom | Fix |
|---|---|
| **No alerts** | `min_note_to_notify` may be too high; check you're inside `active_hours`; read `data/watcher.log`. |
| **"captcha/blocked"** | Open yad2.co.il once in your normal browser, then retry. Keep the interval gentle. Datacenter IPs / VPNs get blocked — use a normal home connection. |
| **launchd never runs (macOS)** | Project must be outside `~/Desktop`/`~/Documents`/`~/Downloads` (TCC). Check `data/launchd.log`. |
| **Empty or wrong results** | The yad2 URL ids are probably off — rebuild on the site, or with `/yad2-search`. |
| **Rebuild AI scoring in another language** | Edit `rating_intro` in `adapters.py`. |

## Commands

```sh
python3 watcher.py --now                # run immediately
python3 watcher.py --dry-run            # fetch + diff, no Telegram, no state writes
python3 watcher.py --setup-telegram     # capture chat_id
python3 watcher.py --install-schedule   # schedule via launchd/cron
python3 watcher.py --uninstall-schedule # stop the schedule
tail -f data/watcher.log                # what each cycle did
```
