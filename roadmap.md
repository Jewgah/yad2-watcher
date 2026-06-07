# yad2-watcher — roadmap

## Checklist

- [x] Validate yad2 access path (noscript=1 cookie beats ShieldSquare; legacy gw API is dead)
- [x] Validate model IDs against yad2 echo (19/13238 = Toyota Prius Plus, 30/10381 = Mitsubishi Outlander, 38/10518 = Citroën C4)
- [x] Watcher core: fetch → `__NEXT_DATA__` parse → token diff → Telegram notify
- [x] Client-side filters (engine, submodel/seats) for what yad2 URLs can't express
- [x] Captcha streak detection + Telegram alert at 5 consecutive blocks
- [x] launchd plist (30 min interval, active-hours guard + jitter in script)
- [x] Bot created (@jordiyad2bot) + token wired + chat linked
- [x] Notifications routed to shared group "Jordi & Lysou" (chat_id -5055696145) so both partners get listings
- [x] launchd job loaded and first run verified LIVE (digests delivered to group 2026-06-07 15:40)
- [ ] Jordan: replace topArea=25 URLs with ville=חדרה + rayon 30-40km URLs from browser
- [ ] After a week: tune filters based on hit quality (false positives / misses)

## Changelog

- **2026-06-07** — Gone LIVE. Project moved Desktop→~/Projects (launchd jobs get TCC
  "Operation not permitted" on Desktop/Documents/Downloads — plist paths updated).
  Notifications switched to the shared couple group; --setup-telegram now also scans
  my_chat_member updates (group joins don't arrive as "message" events).
- **2026-06-07** — Pre-commit review fixes: seeded flag (0-listing search would re-send
  the start digest every cycle), config.json gitignored + config.example.json added
  (token would have landed in git history), km/price formatting hardened against
  non-int types, Telegram send failures now retry next cycle instead of losing the
  listing, --setup-telegram handles unreachable API / rejected token cleanly.
- **2026-06-07** — Initial build. Multi-search watcher (Prius+ active, Outlander essence
  7pl active, C4 disabled), Telegram notifications, launchd scheduling. Tested live
  against yad2: Outlander North = 51 listings parsed; Prius+ North currently 0 (watcher
  will catch the first one); rapid successive requests confirmed to trigger captcha →
  20–40s spacing between searches + 0–90s jitter per cycle.
