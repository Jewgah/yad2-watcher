# yad2-watcher

Polls yad2.co.il vehicle searches every 30 min (08:00–22:00) and sends a Telegram
message for every new listing. Bypasses the Radware/ShieldSquare challenge with the
`noscript=1` cookie trick — yad2 then serves a no-JS page whose `__NEXT_DATA__`
contains the full feed JSON. No dependencies (Python 3 stdlib + curl).

## Setup (one-time)

1. **Create the Telegram bot**: talk to [@BotFather](https://t.me/BotFather) →
   `/newbot` → pick a name → copy the API token into `config.json` → `telegram.api_token`.
2. **Link your chat**: send any message to your new bot in Telegram, then:
   ```sh
   python3 watcher.py --setup-telegram
   ```
   This captures your `chat_id` into `config.json` and sends a confirmation message.
3. **Load the launchd job**:
   ```sh
   cp com.jordan.yad2watcher.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.jordan.yad2watcher.plist
   ```

## Tuning the searches

Each entry in `config.json` → `searches` is one watcher:

- `url` — build the exact search on yad2.co.il in your browser (model, year, price,
  km, region — e.g. ville חדרה + rayon 40 km) and paste the URL here. The watcher
  reads page 1 only (40 listings), so keep filters tight.
- `client_filters` — applied on top of the URL, against the feed JSON:
  - `engine_contains` — e.g. `"בנזין"` (also matches plug-in essence)
  - `submodel_contains` — e.g. `"7 מק"` for 7-seaters. NB: some trims don't state
    seat count (e.g. "Elite אוט׳ 2.0") and would be filtered out — remove the filter
    to see everything.
- `disabled: true` — pause a watcher without deleting it.

First run of each watcher seeds the state and sends a digest (count + 5 cheapest);
after that, only genuinely new listings notify.

## Operations

```sh
python3 watcher.py --now        # run immediately (no jitter, ignores active hours)
python3 watcher.py --dry-run    # fetch + diff, but no Telegram and no state writes
tail -f data/watcher.log        # see what each cycle did
```

State lives in `data/seen_<topic>.json` (listing tokens already notified). Delete a
file to re-seed that watcher. If yad2 blocks 5 cycles in a row you get a Telegram
warning — the usual fix is waiting an hour, or opening yad2 once in your browser.
