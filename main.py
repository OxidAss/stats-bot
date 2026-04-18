import os
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# === Настройки ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-app.onrender.com")  # Без слэша в конце
SECRET_TOKEN = os.getenv("WEBHOOK_SECRET", "render-secret-123")  # Для защиты вебхука
PORT = int(os.getenv("PORT", 8000))

# === Логирование ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Инициализация ===
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

# === Хранилище статистики: {chat_id: {user_id: {"count": int, "week_start": datetime}}} ===
stats_store: dict[int, dict[int, dict]] = defaultdict(lambda: defaultdict(lambda: {"count": 0, "week_start": None}))


def get_week_start_utc() -> datetime:
    """Возвращает понедельник 00:00:00 по UTC"""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def reset_week_if_needed(chat_id: int, user_id: int):
    """Сбрасывает счётчик, если началась новая неделя"""
    current_week_start = get_week_start_utc()
    stored = stats_store[chat_id][user_id]
    
    if stored["week_start"] is None or stored["week_start"] < current_week_start:
        stored["count"] = 0
        stored["week_start"] = current_week_start


@app.on_event("startup")
async def on_startup():
    """Установка вебхука при старте"""
    webhook_info = await bot.get_webhook_info()
    expected_url = f"{WEBHOOK_URL}/webhook/{SECRET_TOKEN}"
    
    if webhook_info.url != expected_url:
        await bot.set_webhook(
            url=expected_url,
            secret_token=SECRET_TOKEN,
            allowed_updates=dp.resolve_used_update_types()
        )
        logger.info(f"✅ Вебхук установлен: {expected_url}")


@app.post("/webhook/{secret}")
async def telegram_webhook(request: Request, secret: str):
    """Обработчик вебхука от Telegram"""
    if secret != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/health")
async def health_check():
    """Эндпоинт для проверки работоспособности на Render"""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@dp.message(Command("флуд_статистика"))
async def cmd_flood_stats(message: Message):
    """Команда: показывает статистику за текущую неделю"""
    chat_id = message.chat.id
    current_week_start = get_week_start_utc()
    
    # Фильтруем только актуальные данные за текущую неделю
    chat_stats = {
        uid: data["count"] 
        for uid, data in stats_store[chat_id].items() 
        if data["week_start"] and data["week_start"] >= current_week_start
    }
    
    if not chat_stats:
        await message.answer("📭 За эту неделю сообщений ещё не было.")
        return
    
    # Сортировка по убыванию
    sorted_stats = sorted(chat_stats.items(), key=lambda x: x[1], reverse=True)
    
    # Формирование ответа
    lines = ["Статистика за неделю:"]
    for user_id, count in sorted_stats:
        try:
            member = await message.bot.get_chat_member(chat_id, user_id)
            name = member.user.first_name
            if member.user.last_name:
                name += f" {member.user.last_name}"
            username = member.user.username
            display_name = f"@{username}" if username else name
        except:
            display_name = f"Пользователь {user_id}"
        lines.append(f"{display_name}: {count}")
    
    response = "\n".join(lines)
    
    # Обрезка если > 4096 символов (лимит Telegram)
    if len(response) > 4090:
        response = response[:4087] + "..."
    
    await message.answer(response)


@dp.message()
async def handle_flood_stats_request(message: Message):
    """Реагирует на текст 'флуд статистика' в любом регистре"""
    
    # Проверяем, что это текст и он совпадает (после приведения к нижнему регистру)
    if not message.text:
        return
    
    if message.text.strip().lower() != "флуд статистика":
        return  # Игнорируем другие сообщения
    
    # === Дальше — логика показа статистики ===
    chat_id = message.chat.id
    current_week_start = get_week_start_utc()
    
    # Фильтруем актуальные данные за текущую неделю
    chat_stats = {
        uid: data["count"] 
        for uid, data in stats_store[chat_id].items() 
        if data["week_start"] and data["week_start"] >= current_week_start
    }
    
    if not chat_stats:
        await message.answer("📭 За эту неделю сообщений ещё не было.")
        return
    
    # Сортировка по убыванию
    sorted_stats = sorted(chat_stats.items(), key=lambda x: x[1], reverse=True)
    
    # Формирование ответа
    lines = ["Статистика за неделю:"]
    for user_id, count in sorted_stats:
        try:
            member = await message.bot.get_chat_member(chat_id, user_id)
            name = member.user.first_name
            if member.user.last_name:
                name += f" {member.user.last_name}"
            username = member.user.username
            display_name = f"@{username}" if username else name
        except:
            display_name = f"Пользователь {user_id}"
        lines.append(f"{display_name}: {count}")
    
    response = "\n".join(lines)
    
    # Обрезка если > 4096 символов (лимит Telegram)
    if len(response) > 4090:
        response = response[:4087] + "..."
    
    await message.answer(response)


# === Запуск для Render (uvicorn) ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
