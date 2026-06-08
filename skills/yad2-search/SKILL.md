---
name: yad2-search
description: Build a yad2-watcher search from a plain-English description — look up the REAL yad2 IDs, construct the search URL plus client_filters, and add the entry to config.json. Use when the user wants help creating or refining a yad2-watcher search instead of hand-building the URL on the site.
---

# yad2-search — natural-language search builder for yad2-watcher

Turn a plain description ("reliable 7-seat petrol SUV under ₪80k near Netanya, 2015+")
into a `searches[]` entry in the project's `config.json`, using the **real** yad2 IDs —
never guessed.

> Run this from inside a `yad2-watcher` checkout (so `config.json` is here).

## Steps

1. **Parse the ask.** Decide the vertical (`cars` or `rentals`) and extract every
   constraint: make/model, year range, price ceiling, km ceiling, seats, fuel/body,
   rooms/size, area/city, and any text-only nuance ("petrol only", "renovated", "private").

2. **Ground the IDs — never invent them.** yad2 URLs use opaque numeric IDs
   (`manufacturer=`, `model=`, `area=`). Get the correct ones:
   - **WebSearch / WebFetch:** `yad2.co.il vehicles cars <model name, EN or HE>` — yad2
     has a canonical indexed URL per model carrying its `manufacturer`/`model` ids. Open
     it and read the ids off the URL/page.
   - **Areas:** fetch a yad2 search page for the city and read the `area=` ids (finer than
     `topArea=`); they're comma-separated for multiple areas.
   - If you cannot verify an id, **stop and ask** the user to paste the category URL they
     get on the site. A wrong id = a silently empty or wrong search. Do not guess.

3. **Build the URL** from verified params:
   - **cars:** `manufacturer`, `model`, `year=YYYY-YYYY`, `price=-1-MAX`, `km=-1-MAX`,
     `seats`, `area=<ids>`.
   - **rentals:** `area=<ids>`, `price=-1-MAX`, `rooms=MIN-MAX`.
   Prefer a real URL param when one exists (e.g. `seats=7` beats a text filter).

4. **Add `client_filters`** for what the URL can't express — post-fetch substring rules
   on parsed fields, no ids needed: e.g. `{"engine_contains": "בנזין"}` (petrol),
   `{"property_contains": "..."}`. Keep them minimal.

5. **Show the proposed entry** (`topic`, `category`, `url`, `client_filters`), explain each
   choice, and confirm with the user before writing.

6. **Append it to `config.json`** under `searches[]` on confirmation (preserve existing
   entries and valid JSON). Then tell them to seed it:
   ```sh
   python3 watcher.py --now
   ```

## Rules
- Verify every id against yad2 (web) — hallucinated ids are the #1 failure mode.
- `topic` is short and human ("Outlander 7-seat petrol").
- The watcher reads **page 1 only**, so keep filters tight enough to fit the best matches.
- One search = one `searches[]` entry.

## Install (one-time, for users)
Copy this folder into your Claude Code skills dir, then invoke `/yad2-search`:
```sh
cp -r skills/yad2-search ~/.claude/skills/
```
