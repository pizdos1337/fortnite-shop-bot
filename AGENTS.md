# fortnite-shop-bot

Telegram-бот (aiogram 3): пользователь ищет предмет по названию, добавляет в список желаемого,
бот каждые 10 минут проверяет магазин (меняется в 00:00 UTC) и шлёт совпадения с ценой и картинкой.

- Данные: fortnite-api.com, без ключа. История магазина и gameplayTags есть ТОЛЬКО с `responseFlags=7`.
- Каталог (`catalog.py: can_be_in_shop`): есть shopHistory ИЛИ тег `Cosmetics.Source.ItemShop`;
  имена null/TBD отсекаются. ~9.7 тыс. предметов. Кэш `data/catalog.json`, обновляется раз в сутки и при смене магазина.
- `data/users.json`: chat_id -> {wish: [id], notified: дата магазина}. Повторно за один день не уведомляет.
- `config.json`: bot_token, allowed_users (пусто = все), proxy.
- Только косметика BR: треки Jam, машины, инструменты не включены.
- Хостинг bothost.ru (деплой из git): токен из env `BOT_TOKEN` (платформа подставляет сама), данные в `DATA_DIR=/app/data`
  (только она переживает пересборку). Каталог качается на диск и читается потоком через ijson: пик ~21 МБ (лимит free 256 МБ).
  Необязательные env: `ALLOWED_USERS` (через запятую), `PROXY`.
