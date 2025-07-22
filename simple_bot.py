"""HD | Lookism Telegram Bot - Simplified version for testing."""

import os
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")

if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
    print("❌ Ошибка: BOT_TOKEN не найден в .env файле!")
    print("📝 Добавьте ваш токен бота в файл .env:")
    print("BOT_TOKEN=ваш_токен_от_BotFather")
    exit(1)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Simple in-memory storage for demo
users_data = {}

class PhotoStates(StatesGroup):
    """States for photo upload flow."""
    waiting_front = State()
    waiting_profile = State()


def get_user_data(user_id: int) -> dict:
    """Get or create user data."""
    if user_id not in users_data:
        users_data[user_id] = {
            "is_active": False,
            "analyses_left": 0,
            "messages_left": 0,
            "active_until": None
        }
    return users_data[user_id]


def is_user_active(user_data: dict) -> bool:
    """Check if user has active subscription."""
    if not user_data.get("active_until"):
        return False
    return datetime.now() < user_data["active_until"]


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    user_data = get_user_data(message.from_user.id)
    
    if is_user_active(user_data):
        await message.answer(
            "🔥 <b>HD | Lookism</b> - твой персональный looksmax коуч!\n\n"
            "📸 Отправь два фото (анфас и профиль) для анализа\n"
            "💬 Получи детальный отчёт и план улучшений\n"
            "🎯 Задавай вопросы нашему ИИ-коучу\n\n"
            f"📊 Осталось анализов: <b>{user_data['analyses_left']}</b>\n"
            f"💬 Осталось сообщений: <b>{user_data['messages_left']}</b>",
            parse_mode="HTML"
        )
    else:
        # Demo activation button
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Активировать ДЕМО (бесплатно)", callback_data="demo_activate")]
        ])
        
        await message.answer(
            "🔥 <b>HD | Lookism</b> - твой персональный looksmax коуч!\n\n"
            "📸 Загружай фото анфас и профиль\n"
            "📊 Получай детальный анализ метрик\n"
            "🎯 Узнавай свой PSL рейтинг\n"
            "💪 Получай план улучшений\n"
            "💬 Общайся с ИИ-коучем\n\n"
            "💰 <b>Подписка: 999 ₽/месяц</b>\n"
            "✅ 3 анализа + 200 сообщений\n\n"
            "🎯 <b>Для тестирования доступна ДЕМО версия</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )


@dp.callback_query(F.data == "demo_activate")
async def demo_activate(callback_query):
    """Activate demo version."""
    user_data = get_user_data(callback_query.from_user.id)
    
    # Activate demo for 1 day with 1 analysis
    user_data["is_active"] = True
    user_data["analyses_left"] = 1
    user_data["messages_left"] = 10
    user_data["active_until"] = datetime.now() + timedelta(days=1)
    
    await callback_query.message.edit_text(
        "🎉 <b>ДЕМО версия активирована!</b>\n\n"
        "✅ 1 анализ\n"
        "✅ 10 сообщений\n"
        "✅ 24 часа доступа\n\n"
        "📸 Отправьте два фото для начала анализа!\n"
        "1️⃣ Фото анфас (лицом к камере)\n"
        "2️⃣ Фото профиль (боком к камере)",
        parse_mode="HTML"
    )
    
    await callback_query.answer("Демо активирована! 🎉")


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Show user statistics."""
    user_data = get_user_data(message.from_user.id)
    
    if not is_user_active(user_data):
        await message.answer("❌ У вас нет активной подписки. Используйте /start для активации.")
        return
    
    days_left = (user_data["active_until"] - datetime.now()).days
    
    await message.answer(
        f"📊 <b>Ваша статистика:</b>\n\n"
        f"⏰ Дней до окончания: <b>{days_left}</b>\n"
        f"📸 Анализов осталось: <b>{user_data['analyses_left']}</b>\n"
        f"💬 Сообщений осталось: <b>{user_data['messages_left']}</b>",
        parse_mode="HTML"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Show help information."""
    await message.answer(
        "🆘 <b>Помощь HD | Lookism</b>\n\n"
        "📸 <b>Как пользоваться:</b>\n"
        "1. Отправьте фото анфас (лицом к камере)\n"
        "2. Отправьте фото профиль (боком к камере)\n"
        "3. Получите детальный анализ\n"
        "4. Задавайте вопросы ИИ-коучу\n\n"
        "⚙️ <b>Команды:</b>\n"
        "/start - Начать работу\n"
        "/stats - Показать статистику\n"
        "/help - Эта справка\n\n"
        "🎯 <b>Демо версия:</b> 1 анализ + 10 сообщений на 24 часа",
        parse_mode="HTML"
    )


@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Handle photo uploads."""
    user_data = get_user_data(message.from_user.id)
    
    if not is_user_active(user_data):
        await message.answer("❌ У вас нет активной подписки. Используйте /start для активации.")
        return
    
    if user_data["analyses_left"] <= 0:
        await message.answer("❌ У вас закончились анализы. Используйте /start для продления.")
        return
    
    current_state = await state.get_state()
    
    if current_state is None:
        # First photo - front
        await state.update_data(front_file_id=message.photo[-1].file_id)
        await state.set_state(PhotoStates.waiting_profile)
        
        await message.answer(
            "✅ Фото анфас принято!\n\n"
            "📸 <b>Шаг 2/2: Профиль</b>\n"
            "Отправьте фото в профиль (боком к камере)"
        )
    
    elif current_state == PhotoStates.waiting_profile:
        # Second photo - profile
        data = await state.get_data()
        front_file_id = data.get("front_file_id")
        
        if not front_file_id:
            await message.answer("❌ Ошибка: не найдено фото анфас. Начните заново.")
            await state.clear()
            return
        
        # Update user quotas
        user_data["analyses_left"] -= 1
        
        await state.clear()
        
        await message.answer(
            "✅ Оба фото получены!\n\n"
            "⏳ Анализ запущен... Это займёт 1-2 минуты\n"
            "🔬 Обрабатываем ваши фото с помощью ИИ\n\n"
            "⚠️ <b>ДЕМО версия:</b> Полный анализ будет доступен после настройки API ключей"
        )
        
        # Simulate analysis delay
        await asyncio.sleep(3)
        
        # Send demo report
        demo_report = """🎉 <b>Анализ готов!</b>

🏷️ РЕЙТИНГ И КАТЕГОРИЯ  
Базовый рейтинг: 6.2/10 | Компонентный: 6.5/10 | Категория: HTN

### 📊 ДЕТАЛЬНЫЙ АНАЛИЗ МЕТРИК  
• Кантальный тилт: +2.3° (хорошо)
• Гониальный угол: 118° (близко к идеалу)
• Пропорции лица: верх 32%, середина 35%, низ 33%
• Симметрия: 7.8/10 (хорошая)
• Проекция подбородка: нормальная

### 💬 ЧЕСТНАЯ ОЦЕНКА  
У вас хорошие базовые пропорции лица и неплохая симметрия. Основные области для улучшения - это работа над кантальным тилтом и общим тонусом лица.

### 📌 ДЕТАЛЬНЫЙ ПЛАН УЛУЧШЕНИЙ  
**Немедленные (0-3 месяца):**
- Мьюинг для улучшения челюстной линии
- Упражнения для глаз
- Уход за кожей

**Среднесрочные (3-12 месяцев):**
- Жевательные упражнения
- Массаж лица
- Правильная осанка

**Долгосрочные (1+ год):**
- Рассмотреть консультацию специалиста
- Возможные процедуры коррекции

### 🔍 КОНКРЕТНЫЕ ПРОДУКТЫ  
- Жвачка Falim для развития массетеров
- Коллаген для упругости кожи
- Витамин D3 + K2 для костной структуры

💬 Теперь можешь задавать вопросы!

⚠️ <b>Это демо-отчёт. Для реального анализа нужны API ключи Face++, AILab и DeepSeek.</b>"""
        
        await message.answer(demo_report, parse_mode="HTML")


@dp.message(F.text)
async def handle_text(message: Message):
    """Handle text messages (Q&A)."""
    user_data = get_user_data(message.from_user.id)
    
    if not is_user_active(user_data):
        await message.answer("❌ У вас нет активной подписки. Используйте /start для активации.")
        return
    
    if user_data["messages_left"] <= 0:
        await message.answer("❌ У вас закончились сообщения. Используйте /start для продления.")
        return
    
    # Update message count
    user_data["messages_left"] -= 1
    
    # Simple demo responses
    user_text = message.text.lower()
    
    if "мьюинг" in user_text or "mewing" in user_text:
        response = """💪 <b>Мьюинг (Mewing)</b>

🎯 <b>Что это:</b>
Правильная позиция языка для улучшения челюстной линии и профиля лица.

📋 <b>Как делать:</b>
1. Прижми весь язык к нёбу
2. Держи постоянно (24/7)
3. Дыши через нос
4. Не напрягай шею

⏰ <b>Результаты:</b>
Первые изменения через 3-6 месяцев регулярной практики.

💡 <b>Совет:</b> Начинай постепенно, чтобы избежать боли в челюсти."""
    
    elif "жвачка" in user_text or "массетер" in user_text:
        response = """🦷 <b>Жевательные упражнения</b>

🎯 <b>Цель:</b>
Развитие массетеров для более выраженной челюстной линии.

📋 <b>Рекомендации:</b>
• Жвачка Falim (самая жёсткая)
• 30-60 минут в день
• Равномерно на обе стороны
• Перерывы между сессиями

⚠️ <b>Осторожно:</b>
Не переусердствуй - можешь повредить челюстной сустав."""
    
    elif "кожа" in user_text or "уход" in user_text:
        response = """✨ <b>Уход за кожей лица</b>

🧴 <b>Базовый уход:</b>
1. Очищение (утром и вечером)
2. Тонизирование
3. Увлажнение
4. SPF защита (днём)

🔬 <b>Активные компоненты:</b>
• Ретинол (вечером)
• Витамин C (утром)
• Ниацинамид (универсально)
• Гиалуроновая кислота

💡 <b>Совет:</b>
Вводи новые продукты постепенно."""
    
    else:
        response = f"""💬 <b>Вопрос принят!</b>

Ваш вопрос: "{message.text}"

⚠️ <b>Демо режим:</b> Для полноценного ИИ-коуча нужен API ключ DeepSeek.

🎯 <b>Популярные темы:</b>
• Мьюинг и техники
• Жевательные упражнения
• Уход за кожей
• Добавки и питание

💬 Осталось сообщений: <b>{user_data['messages_left']}</b>"""
    
    await message.answer(response, parse_mode="HTML")


async def main():
    """Main entry point."""
    logger.info("🚀 Запуск HD | Lookism бота (демо версия)...")
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
