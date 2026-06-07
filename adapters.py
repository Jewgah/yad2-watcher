"""
Vertical adapters for yad2-watcher.

The engine (watcher.py) is category-agnostic: it fetches a yad2 search page,
extracts the __NEXT_DATA__ feed, diffs tokens, rates, and notifies. Everything
that differs between a car search and an apartment search lives here:

  extract(item)        -> normalized listing dict from one feed entry
  enrich(data, l)      -> merge fields from the listing's own item page (or None to skip)
  format(l)            -> the Telegram message body
  rating_intro(topic)  -> the buyer-context + scoring rules fed to the rater
  emoji                -> header/notification emoji
  item_url(token)      -> the per-listing detail-page URL (for enrichment + the link)

Add a new vertical by writing one entry in ADAPTERS — the engine needs no changes.
"""


# ---------------------------------------------------------------- cars

def _cars_extract(it):
    token = it.get("token")
    return {
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
        "url": _cars_item_url(token),
    }


def _cars_item_url(token):
    return f"https://www.yad2.co.il/vehicles/item/{token}"


def _cars_find_item(data):
    """Locate the single-listing object inside an item page's __NEXT_DATA__."""
    try:
        for q in data["props"]["pageProps"]["dehydratedState"]["queries"]:
            d = q.get("state", {}).get("data")
            if isinstance(d, dict) and "km" in d and "price" in d:
                return d
    except (KeyError, TypeError):
        return None
    return None


def _cars_enrich(data, l):
    item = _cars_find_item(data)
    if item is None:
        return l
    l = dict(l)
    if isinstance(item.get("km"), int):
        l["km"] = item["km"]
    test = (item.get("vehicleDates") or {}).get("testDate")
    if isinstance(test, str) and test:
        l["test"] = test[:10]
    city = ((item.get("address") or {}).get("city") or {}).get("text")
    if city:
        l["city"] = city
    l["gearbox"] = (item.get("gearBox") or {}).get("text")
    l["color"] = (item.get("color") or {}).get("text")
    agency = (item.get("customer") or {}).get("agencyName")
    l["seller"] = f"סוכנות {agency}" if agency else (
        "מסחרי" if item.get("adType") == "commercial" else "פרטי"
    )
    if item.get("abovePrice") is not None:
        l["above_price_vs_pricelist"] = item["abovePrice"]
    return l


def _cars_format(l):
    km = f"{l['km']:,} km" if isinstance(l.get("km"), int) else "km ?"
    price = f"₪{l['price']:,}" if isinstance(l.get("price"), int) else "₪?"
    where = f"{l['city']} ({l['area']})" if l.get("city") else l.get("area", "?")
    lines = [
        f"{price} | {l.get('year')} | {l.get('hand')} | {km}",
        f"{l.get('model')} — {l.get('submodel')}",
        f"📍 {where} | מנוע: {l.get('engine')}",
    ]
    extras = " | ".join(filter(None, [l.get("gearbox"), l.get("color")]))
    if extras:
        lines.append(extras)
    info = " | ".join(filter(None, [
        f"טסט עד {l['test']}" if l.get("test") else None,
        f"מוכר: {l['seller']}" if l.get("seller") else None,
    ]))
    if info:
        lines.append(info)
    lines.append(l["url"])
    return "\n".join(lines)


def _cars_rating_intro(topic):
    return (
        "Tu es un expert du marché auto d'occasion israélien (yad2). "
        "Contexte acheteur : famille, ~30 000 km/an, cherche un 7 places fiable ≤ 80 000 ₪. "
        f"Recherche active : {topic}. "
        "Règles de notation : km + entretien + état mécanique priment sur l'année ; "
        "vendeur particulier > agence (reprises) ; טסט long = bonus ; "
        "compare le prix au marché israélien réel de ce modèle/année/km."
    )


# ---------------------------------------------------------------- rentals

def _rentals_item_url(token):
    return f"https://www.yad2.co.il/realestate/item/{token}"


def _rentals_extract(it):
    token = it.get("token")
    addr = it.get("address") or {}
    house = addr.get("house") or {}
    details = it.get("additionalDetails") or {}
    street = (addr.get("street") or {}).get("text", "")
    num = house.get("number")
    street_full = f"{street} {num}".strip() if street else ""
    return {
        "token": token,
        "price": it.get("price"),
        "rooms": details.get("roomsCount"),
        "sqm": details.get("squareMeter"),
        "floor": house.get("floor"),
        "property": (details.get("property") or {}).get("text", ""),
        "city": (addr.get("city") or {}).get("text", ""),
        "neighborhood": (addr.get("neighborhood") or {}).get("text", ""),
        "street": street_full,
        "area": (addr.get("area") or {}).get("text", "?"),
        "tags": [t.get("name") for t in (it.get("tags") or []) if t.get("name")],
        "seller": "פרטי" if it.get("adType") == "private" else "תיווך/מסחרי",
        "created": it.get("createdAt", ""),
        "url": _rentals_item_url(token),
    }


def _rentals_format(l):
    price = f"₪{l['price']:,}/חודש" if isinstance(l.get("price"), int) else "₪?/חודש"
    bits = [price]
    if l.get("rooms") is not None:
        bits.append(f"{l['rooms']} חד׳")
    if l.get("sqm"):
        bits.append(f"{l['sqm']} מ״ר")
    if l.get("floor") is not None:
        bits.append(f"קומה {l['floor']}")
    where_line = ", ".join(filter(None, [l.get("street"), l.get("city")]))
    lines = [" | ".join(bits)]
    if l.get("property") or where_line:
        lines.append(" — ".join(filter(None, [l.get("property"), where_line])))
    area_line = " ".join(filter(None, [l.get("neighborhood"), f"({l['area']})" if l.get("area") else ""]))
    if area_line.strip():
        lines.append(f"📍 {area_line.strip()} | {l.get('seller', '')}".rstrip(" |"))
    if l.get("tags"):
        lines.append("🏷️ " + ", ".join(l["tags"][:4]))
    lines.append(l["url"])
    return "\n".join(lines)


def _rentals_rating_intro(topic):
    return (
        "Tu es un expert du marché locatif israélien (yad2 immobilier). "
        f"Recherche active : {topic}. "
        "Évalue si le loyer est juste : compare le ₪/m² au marché réel de CE quartier et de cette taille, "
        "tiens compte de l'étage, de l'état (tags comme 'בניין משופץ' = rénové, 'בהזדמנות' = opportunité), "
        "et des atouts. Particulier > agence (pas de commission). "
        "Note 0-10 (10 = loyer nettement sous le marché pour le quartier, à visiter en priorité)."
    )


# ---------------------------------------------------------------- registry

ADAPTERS = {
    "cars": {
        "emoji": "🚗",
        "extract": _cars_extract,
        "item_url": _cars_item_url,
        "enrich": _cars_enrich,          # fetch each listing's page for km/test/seller
        "format": _cars_format,
        "rating_intro": _cars_rating_intro,
    },
    "rentals": {
        "emoji": "🏠",
        "extract": _rentals_extract,
        "item_url": _rentals_item_url,
        "enrich": None,                  # feed JSON already carries rooms/m²/floor/area — no extra fetch
        "format": _rentals_format,
        "rating_intro": _rentals_rating_intro,
    },
}


def get_adapter(category):
    return ADAPTERS.get(category or "cars", ADAPTERS["cars"])
