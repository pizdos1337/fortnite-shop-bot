"""Telegram-бот: список желаемого из всего, что может появиться в магазине Fortnite,
и уведомление, когда что-то из него сегодня в магазине."""
import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from html import escape

import catalog as C

ROOT = Path(__file__).resolve().parent
# config.json — для запуска у себя; на хостинге всё берётся из переменных окружения
_cfg_file = ROOT / "config.json"
CFG = json.loads(_cfg_file.read_text("utf-8")) if _cfg_file.exists() else {}
CFG["bot_token"] = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
                    or CFG.get("bot_token", ""))
if os.environ.get("ALLOWED_USERS"):
    CFG["allowed_users"] = [int(x) for x in os.environ["ALLOWED_USERS"].replace(",", " ").split()]
if os.environ.get("PROXY"):
    CFG["proxy"] = os.environ["PROXY"]
USERS_FILE = C.DATA / "users.json"
CHECK_EVERY = 10 * 60      # магазин меняется в 00:00 UTC (03:00 МСК), проверяем каждые 10 минут
PAGE = 8

HELP = (
    "<b>Магазин Fortnite</b>\n\n"
    "Напиши название предмета (скин, кирка, эмоция, рюкзак…), и я найду его среди "
    "всего, что когда-либо было или может быть в магазине. Нажми ➕, чтобы добавить "
    "в список желаемого.\n\n"
    "Каждый день после обновления магазина (03:00 МСК) пришлю сообщение, если что-то из "
    "твоего списка там есть.\n\n"
    "/list — мой список\n"
    "/shop — что из моего списка в магазине сейчас\n"
    "/catalog — файл со всем каталогом\n"
)

dp = Dispatcher()
cat: list = []
by_id: dict = {}
shop_date = ""
prices: dict = {}
last_query: dict = {}      # chat_id -> последний поисковый запрос (для листания)
users: dict = {}


def load_users():
    global users
    users = json.loads(USERS_FILE.read_text("utf-8")) if USERS_FILE.exists() else {}


def save_users():
    C.DATA.mkdir(parents=True, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(USERS_FILE)


def user(chat_id) -> dict:
    return users.setdefault(str(chat_id), {"wish": [], "notified": ""})


def allowed(uid) -> bool:
    lst = CFG.get("allowed_users") or []
    return not lst or uid in lst


def set_catalog(new):
    global cat, by_id
    cat, by_id = new, {x["id"]: x for x in new}


# ---------- поиск и список ----------

def search_page(chat_id, query, page):
    res = C.search(cat, query)
    if not res:
        return "Ничего не нашёл. Попробуй часть названия, например «рейдер».", None
    wish = set(user(chat_id)["wish"])
    pages = (len(res) + PAGE - 1) // PAGE
    page = max(0, min(page, pages - 1))
    chunk = res[page * PAGE:(page + 1) * PAGE]
    lines = [f"Найдено: {len(res)}" + (f" (стр. {page + 1}/{pages})" if pages > 1 else "")]
    rows = []
    for i, it in enumerate(chunk, 1 + page * PAGE):
        mark = "✅" if it["id"] in wish else "➕"
        now = " 🛒 СЕЙЧАС В МАГАЗИНЕ" if it["id"] in prices else ""
        lines.append(f"{i}. {escape(C.describe(it))}{now}")
        rows.append([InlineKeyboardButton(text=f"{mark} {i}. {it['name']} · {it['type_name']}"[:60],
                                          callback_data=f"t:{it['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"p:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"p:{page + 1}"))
    if nav:
        rows.append(nav)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def list_view(chat_id):
    wish = user(chat_id)["wish"]
    if not wish:
        return "Список пуст. Напиши название предмета, чтобы найти и добавить.", None
    lines, rows = [f"<b>Мой список ({len(wish)})</b>"], []
    for i, wid in enumerate(wish, 1):
        it = by_id.get(wid)
        name = it["name"] if it else wid
        if it:
            now = f" 🛒 сейчас в магазине, {prices[wid]} В-баксов" if wid in prices else ""
            lines.append(f"{i}. {escape(C.describe(it))}{now}")
        else:
            lines.append(f"{i}. {escape(wid)} (нет в каталоге)")
        rows.append([InlineKeyboardButton(text=f"❌ {i}. {name}"[:60], callback_data=f"r:{wid}")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
@dp.message(Command("help"))
async def start(m: Message):
    if not allowed(m.from_user.id):
        return
    user(m.chat.id)
    save_users()
    await m.answer(HELP + f"\nВ каталоге {len(cat)} предметов.")


@dp.message(Command("list"))
async def cmd_list(m: Message):
    if not allowed(m.from_user.id):
        return
    text, kb = list_view(m.chat.id)
    await m.answer(text, reply_markup=kb)


@dp.message(Command("shop"))
async def cmd_shop(m: Message):
    if not allowed(m.from_user.id):
        return
    hits = [w for w in user(m.chat.id)["wish"] if w in prices]
    if not hits:
        await m.answer(f"Сегодня ({shop_date}) ничего из твоего списка в магазине нет. "
                       f"Всего в магазине {len(prices)} предметов.")
        return
    await send_hits(m.bot, m.chat.id, hits)


@dp.message(Command("catalog"))
async def cmd_catalog(m: Message):
    if not allowed(m.from_user.id):
        return
    data = C.catalog_text(cat).encode("utf-8")
    await m.answer_document(BufferedInputFile(data, "fortnite_catalog.txt"),
                            caption=f"Весь каталог: {len(cat)} предметов. Нужное ищи в чате по названию.")


@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    if not allowed(m.from_user.id):
        return
    last_query[m.chat.id] = m.text
    text, kb = search_page(m.chat.id, m.text, 0)
    await m.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("p:"))
async def on_page(c: CallbackQuery):
    q = last_query.get(c.message.chat.id)
    if not q:
        await c.answer("Повтори поиск")
        return
    text, kb = search_page(c.message.chat.id, q, int(c.data[2:]))
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer()


@dp.callback_query(F.data.startswith("t:"))
async def on_toggle(c: CallbackQuery):
    wid, u = c.data[2:], user(c.message.chat.id)
    it = by_id.get(wid)
    name = it["name"] if it else wid
    if wid in u["wish"]:
        u["wish"].remove(wid)
        note = f"Убрал: {name}"
    else:
        u["wish"].append(wid)
        note = f"Добавил: {name}"
        if wid in prices:
            note += f". Он прямо сейчас в магазине за {prices[wid]} В-баксов!"
    save_users()
    q = last_query.get(c.message.chat.id)
    if q:
        page = 0
        try:  # остаться на той же странице
            txt = c.message.text or ""
            if "стр. " in txt:
                page = int(txt.split("стр. ")[1].split("/")[0]) - 1
        except ValueError:
            pass
        text, kb = search_page(c.message.chat.id, q, page)
        try:
            await c.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
    await c.answer(note, show_alert=wid in prices and wid in u["wish"])


@dp.callback_query(F.data.startswith("r:"))
async def on_remove(c: CallbackQuery):
    wid, u = c.data[2:], user(c.message.chat.id)
    if wid in u["wish"]:
        u["wish"].remove(wid)
        save_users()
    text, kb = list_view(c.message.chat.id)
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer("Убрал")


# ---------- уведомления ----------

async def send_hits(bot: Bot, chat_id, hits):
    lines = [f"🛒 <b>В магазине Fortnite сегодня ({shop_date}) есть из твоего списка:</b>"]
    for wid in hits:
        it = by_id.get(wid)
        lines.append(f"• {escape(it['name'] if it else wid)}"
                     f"{' · ' + escape(it['type_name']) if it else ''} — {prices[wid]} В-баксов")
    await bot.send_message(chat_id, "\n".join(lines))
    for wid in hits[:10]:
        it = by_id.get(wid)
        if it and it["icon"]:
            try:
                await bot.send_photo(chat_id, it["icon"], caption=f"{it['name']} — {prices[wid]} В-баксов")
            except Exception as e:
                logging.warning("фото %s: %s", wid, e)


async def notify_all(bot: Bot):
    changed = False
    for chat_id, u in users.items():
        if u.get("notified") == shop_date:
            continue
        hits = [w for w in u["wish"] if w in prices]
        if hits:
            try:
                await send_hits(bot, int(chat_id), hits)
            except Exception as e:
                logging.warning("уведомление %s: %s", chat_id, e)
                continue
        u["notified"] = shop_date
        changed = True
    if changed:
        save_users()


async def refresh(force_catalog=False):
    global shop_date, prices
    shop = await C.load_shop()
    new_date = shop["date"][:10]
    if new_date != shop_date:
        if shop_date:          # магазин сменился — заодно подтянуть новые предметы
            force_catalog = True
        shop_date, prices = new_date, C.shop_prices(shop)
        logging.info("магазин %s: %d предметов", shop_date, len(prices))
    if force_catalog:
        set_catalog(await C.load_catalog(force=True))


async def watcher(bot: Bot):
    while True:
        await asyncio.sleep(CHECK_EVERY)
        try:
            await refresh()
            await notify_all(bot)
        except Exception as e:
            logging.warning("проверка магазина: %s", e)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    load_users()
    set_catalog(await C.load_catalog())
    logging.info("каталог: %d предметов", len(cat))
    await refresh()
    # если Telegram заблокирован: "proxy": "http://127.0.0.1:порт" или socks5:// (нужен aiohttp-socks)
    session = AiohttpSession(proxy=CFG["proxy"]) if CFG.get("proxy") else None
    bot = Bot(CFG["bot_token"], session=session, default=DefaultBotProperties(parse_mode="HTML"))
    await notify_all(bot)
    asyncio.create_task(watcher(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
