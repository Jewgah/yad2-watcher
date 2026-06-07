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
- [x] Area targeting: area=70,17 (צפון השרון + נתניה) — Jordan's strict choice: Hadera, Netanya, Pardes Hana, Or Akiva; Haifa/Krayot explicitly excluded. NB: vehicles search has no city param (city=X is silently ignored), zones are the finest grain
- [x] Outlander year floor raised to 2017 (wife prefers newer); ceilings later widened to 2020 + price to 80K — strict zones still yield 0 listings for both models (stock lives Haifa-side); watchers armed
- [x] Notification enrichment: each listing's page fetched for real km, טסט date, gearbox, city, color, seller (agency vs private) — best-effort, falls back to basic info on captcha
- [x] seats=7 URL param discovered & verified (echo confirms) — replaces the brittle "7 מק" submodel-text filter that missed 100% of Versos (trims like "GLI אוט׳ 1.8" omit seat count)
- [x] Fleet widened to 7 watchers: + Verso (19/10245), X-Trail (32/10457), Sorento (48/10718), Santa Fe (21/10287), Mazda 5 (27/925) — first hits: X-Trail x4, Santa Fe x2, Sorento x1 in strict zones
- [ ] After a week: tune filters based on hit quality (false positives / misses)

## Changelog

- **2026-06-07** — Corridor + enrichment. Searches narrowed from topArea=25 (all North)
  to area=70,17,5,6 (Hadera↔Netanya↔Haifa↔Krayot corridor; ids read back from yad2's
  feed-literal echo). Outlander floor raised to 2017. Notifications now fetch each
  listing's item page (noscript trick, spaced) and include km / טסט / gearbox / city /
  color / seller — km is THE decision figure and the feed omits it. Re-seeded live:
  enriched digests delivered to the group 15:54.
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
