"""Каталог предметов Fortnite, которые могут появиться в магазине, и разбор магазина дня.

Данные: fortnite-api.com (бесплатно, без ключа).
responseFlags=7 включает gameplayTags и shopHistory (без флага истории нет).
"""
import json
import os
import time
from pathlib import Path

import aiohttp
import ijson

API = "https://fortnite-api.com/v2"
# На bothost DATA_DIR=/app/data — единственная папка, которая переживает пересборку
DATA = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent / "data")
CATALOG_FILE = DATA / "catalog.json"
CATALOG_MAX_AGE = 24 * 3600

# Названия-заглушки у неготовых предметов
JUNK_NAMES = {"null", "tbd", ""}

TYPE_ORDER = ["outfit", "backpack", "pickaxe", "glider", "emote", "wrap", "shoe",
              "contrail", "loadingscreen", "music", "spray", "emoji", "banner",
              "sidekick", "pet", "petcarrier", "aura", "toy"]


def can_be_in_shop(item: dict) -> bool:
    """Был в магазине хоть раз или помечен как магазинный (ещё не выходил).
    Боевые пропуски, промо, награды за задания без истории магазина отсекаются."""
    if (item.get("name") or "").strip().lower() in JUNK_NAMES:
        return False
    if item.get("shopHistory"):
        return True
    return "Cosmetics.Source.ItemShop" in (item.get("gameplayTags") or [])


def build_catalog(raw_items) -> list:
    out = []
    for it in raw_items:
        if not can_be_in_shop(it):
            continue
        hist = it.get("shopHistory") or []
        out.append({
            "id": it["id"],
            "name": it["name"].strip(),
            "type": it["type"]["value"],
            "type_name": it["type"]["displayValue"],
            "rarity": it["rarity"]["displayValue"],
            "set": (it.get("set") or {}).get("value") or "",
            "times": len(hist),
            "last": hist[-1][:10] if hist else "",
            "icon": it["images"].get("icon") or it["images"].get("smallIcon") or "",
        })
    order = {t: i for i, t in enumerate(TYPE_ORDER)}
    out.sort(key=lambda x: (order.get(x["type"], 99), x["name"].lower()))
    return out


async def _get(session, path, params):
    async with session.get(API + path, params=params, timeout=aiohttp.ClientTimeout(total=180)) as r:
        r.raise_for_status()
        return (await r.json())["data"]


async def load_catalog(force=False) -> list:
    """Каталог с диска, раз в сутки обновляется с API (~27 МБ сырых данных)."""
    DATA.mkdir(parents=True, exist_ok=True)
    fresh = CATALOG_FILE.exists() and time.time() - CATALOG_FILE.stat().st_mtime < CATALOG_MAX_AGE
    if fresh and not force:
        return json.loads(CATALOG_FILE.read_text("utf-8"))
    # Ответ ~27 МБ: качаем на диск и разбираем потоком, иначе не влезает в 256 МБ хостинга
    raw_file = DATA / "cosmetics_raw.json"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(API + "/cosmetics/br", params={"language": "ru", "responseFlags": "7"},
                             timeout=aiohttp.ClientTimeout(total=300)) as r:
                r.raise_for_status()
                with open(raw_file, "wb") as f:
                    async for chunk in r.content.iter_chunked(1 << 16):
                        f.write(chunk)
        with open(raw_file, "rb") as f:
            cat = build_catalog(ijson.items(f, "data.item", use_float=True))
    except Exception:
        if CATALOG_FILE.exists():          # API лежит — работаем со старым
            return json.loads(CATALOG_FILE.read_text("utf-8"))
        raise
    finally:
        raw_file.unlink(missing_ok=True)
    CATALOG_FILE.write_text(json.dumps(cat, ensure_ascii=False), "utf-8")
    return cat


async def load_shop() -> dict:
    async with aiohttp.ClientSession() as s:
        return await _get(s, "/shop", {"language": "ru"})


def shop_prices(shop: dict) -> dict:
    """id предмета -> {"single": цена отдельно или None, "bundle": (название набора, цена) или None}.
    Предмет может продаваться отдельно, в наборе или и так и так; берём самые дешёвые варианты."""
    offers = {}
    for e in shop.get("entries") or []:
        p = e.get("finalPrice", 0)
        bundle = (e.get("bundle") or {}).get("name")
        for it in e.get("brItems") or []:
            o = offers.setdefault(it["id"], {"single": None, "bundle": None})
            if bundle:
                if o["bundle"] is None or p < o["bundle"][1]:
                    o["bundle"] = (bundle, p)
            elif o["single"] is None or p < o["single"]:
                o["single"] = p
    return offers


def offer_text(o: dict) -> str:
    if o["bundle"]:
        name, price = o["bundle"]
        if "«" not in name:            # «Комплект «Хацунэ Мику»» — двойные кавычки ни к чему
            name = f"«{name}»"
    if o["single"] is not None:
        s = f"{o['single']} В-баксов"
        if o["bundle"]:
            s += f" (также в наборе {name} за {price})"
        return s
    return f"только в наборе {name} за {price} В-баксов"


def _norm(s: str) -> str:
    return s.lower().replace("ё", "е").strip()


def search(catalog: list, query: str) -> list:
    """Сначала точные совпадения названия, потом начинающиеся с запроса, потом содержащие."""
    q = _norm(query)
    if not q:
        return []
    exact, starts, contains = [], [], []
    for it in catalog:
        n = _norm(it["name"])
        if n == q:
            exact.append(it)
        elif n.startswith(q):
            starts.append(it)
        elif q in n or q in _norm(it["set"]) or q == it["id"].lower():
            contains.append(it)
    return exact + starts + contains


def describe(it: dict) -> str:
    seen = f"был в магазине {it['times']} раз, последний — {it['last']}" if it["times"] \
        else "в магазине ещё не появлялся"
    return f"{it['name']} · {it['type_name']} · {it['rarity']} ({seen})"


def catalog_text(catalog: list) -> str:
    """Полный список одним текстом: по типам, с датой последнего появления."""
    lines, cur = [], None
    for it in catalog:
        if it["type"] != cur:
            cur = it["type"]
            n = sum(1 for x in catalog if x["type"] == cur)
            lines.append(f"\n===== {it['type_name']} ({n}) =====")
        last = f"последний раз {it['last']}, всего {it['times']}" if it["times"] else "ещё не выходил"
        set_ = f" [{it['set']}]" if it["set"] else ""
        lines.append(f"{it['name']}{set_} — {it['rarity']}, {last}")
    head = (f"Все предметы Fortnite, которые могут появиться в магазине: {len(catalog)}.\n"
            "Без наград боевых пропусков, промо и прочих, которых в магазине не бывает.\n")
    return head + "\n".join(lines) + "\n"
