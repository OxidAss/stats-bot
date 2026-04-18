import os
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
import uvicorn

# === НАСТРОЙКИ ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-app.onrender.com")
SECRET_TOKEN = os.getenv("WEBHOOK_SECRET", "render-secret-123")
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

# Хранилище: {chat_id: {user_id: {"count": int, "display_name": str, "week_start": datetime}}}
stats_store = defaultdict(lambda: defaultdict(lambda: {"count": 0, "display_name": "", "week_start": None}))

def get_monday_utc() -> datetime:
    """Возвращает понедельник текущей недели 00:00:00 UTC"""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)

@app.on_event("startup")
async def on_startup():
    webhook_info = await bot.get_webhook_info()
    expected_url = f"{WEBHOOK_URL}/webhook/{SECRET_TOKEN}"
    if webhook_info.url != expected_url:
        await bot.set_webhook(
            url=expected_url,
            secret_token=SECRET_TOKEN,
            allowed_updates=dp.resolve_used_update_types()
        )
        logging.info(f"✅ Вебхук установлен: {expected_url}")

@app.post("/webhook/{secret}")
async def telegram_webhook(request: Request, secret: str):
    if secret != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@dp.message()
async def handle_message(message: Message):
    # Игнорируем ботов, сервисные сообщения и пустые
    if not message.text or message.from_user.is_bot or message.from_user.id == bot.id:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    current_week_start = get_monday_utc()

    # Инициализация/сброс счётчика при смене недели
    user_data = stats_store[chat_id][user_id]
    if user_data["week_start"] is None or user_data["week_start"] < current_week_start:
        user_data["count"] = 0
        user_data["week_start"] = current_week_start

    # Кэшируем отображаемое имя при первом сообщении (избегаем лишних запросов к API)
    if not user_data["display_name"]:
        name = message.from_user.first_name or "Без имени"
        if message.from_user.last_name:
            name += f" {message.from_user.last_name}"
        user_data["display_name"] = f"@{message.from_user.username}" if message.from_user.username else name

    # Проверяем команду
    is_stats_cmd = message.text.strip().lower() == "флуд статистика"

    # Если НЕ команда -> считаем сообщение
    if not is_stats_cmd:
        user_data["count"] += 1
        return

    # === ГЕНЕРАЦИЯ СТАТИСТИКИ В РЕАЛЬНОМ ВРЕМЕНИ ===
    week_start = get_monday_utc()
    now = datetime.now(timezone.utc)
    
    # Фильтруем только актуальных пользователей за текущую неделю
    active_users = []
    for uid, data in stats_store[chat_id].items():
        if data.get("week_start") and data["week_start"] >= week_start and data["count"] > 0:
            active_users.append((data["display_name"], data["count"]))

    if not active_users:
        await message.answer("📭 За эту неделю сообщений ещё не было.")
        return

    # Сортировка по убыванию
    active_users.sort(key=lambda x: x[1], reverse=True)

    # Форматирование периода
    start_fmt = week_start.strftime("%d.%m %H:%M")
    end_fmt = now.strftime("%d.%m %H:%M")
    
    lines = [f"📊 Статистика за неделю ({start_fmt} - {end_fmt} UTC):"]
    for name, count in active_users:
        lines.append(f"👤 {name}: {count}")

    response = "\n".join(lines)
    if len(response) > 4090:
        response = response[:4087] + "\n⏳ ..."

    await message.answer(response)

# === ЗАПУСК ДЛЯ RENDER ===
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
