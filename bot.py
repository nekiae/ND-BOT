"""HD | Lookism Telegram Bot - Main bot implementation."""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session, create_db_and_tables
from models import User, Session, SessionStatus
from validators import validate_front_photo, validate_profile_photo, validate_image_quality
from task_queue import task_queue, init_queue
from payments import payment_manager
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
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PAYMENT_WEBHOOK_PATH = os.getenv("PAYMENT_WEBHOOK_PATH", "/payment/webhook")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables")

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


class PhotoStates(StatesGroup):
    """States for photo upload flow."""
    waiting_front = State()
    waiting_profile = State()


async def get_or_create_user(user_id: int) -> User:
    """Get or create user in database."""
    async for db_session in get_session():
        user = await db_session.get(User, user_id)
        if not user:
            user = User(id=user_id)
            db_session.add(user)
            await db_session.commit()
            await db_session.refresh(user)
        return user


def is_user_active(user: User) -> bool:
    """Check if user has active subscription."""
    if not user.is_active_until:
        return False
    return datetime.utcnow() < user.is_active_until


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    user = await get_or_create_user(message.from_user.id)
    
    if is_user_active(user):
        await message.answer(
            "🔥 <b>HD | Lookism</b> - твой персональный looksmax коуч!\n\n"
            "📸 Отправь два фото (анфас и профиль) для анализа\n"
            "💬 Получи детальный отчёт и план улучшений\n"
            "🎯 Задавай вопросы нашему ИИ-коучу\n\n"
            f"📊 Осталось анализов: <b>{user.analyses_left}</b>\n"
            f"💬 Осталось сообщений: <b>{user.messages_left}</b>",
            parse_mode="HTML"
        )
    else:
        # Create payment button
        payment_url = payment_manager.create_payment_url(
            user_id=message.from_user.id,
            return_url=f"{WEBHOOK_URL}/payment/success"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить 999 ₽", url=payment_url)]
        ])
        
        await message.answer(
            "🔥 <b>HD | Lookism</b> - твой персональный looksmax коуч!\n\n"
            "📸 Загружай фото анфас и профиль\n"
            "📊 Получай детальный анализ метрик\n"
            "🎯 Узнавай свой PSL рейтинг\n"
            "💪 Получай план улучшений\n"
            "💬 Общайся с ИИ-коучем\n\n"
            "💰 <b>Подписка: 999 ₽/месяц</b>\n"
            "✅ 3 анализа + 200 сообщений",
            reply_markup=keyboard,
            parse_mode="HTML"
        )


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Show user statistics."""
    user = await get_or_create_user(message.from_user.id)
    
    if not is_user_active(user):
        await message.answer("❌ У вас нет активной подписки. Используйте /start для оплаты.")
        return
    
    days_left = (user.is_active_until - datetime.utcnow()).days
    
    await message.answer(
        f"📊 <b>Ваша статистика:</b>\n\n"
        f"⏰ Дней до окончания: <b>{days_left}</b>\n"
        f"📸 Анализов осталось: <b>{user.analyses_left}</b>\n"
        f"💬 Сообщений осталось: <b>{user.messages_left}</b>",
        parse_mode="HTML"
    )


@dp.message(Command("renew"))
async def cmd_renew(message: Message):
    """Renew subscription."""
    payment_url = payment_manager.create_payment_url(
        user_id=message.from_user.id,
        return_url=f"{WEBHOOK_URL}/payment/success"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Продлить за 999 ₽", url=payment_url)]
    ])
    
    await message.answer(
        "🔄 <b>Продление подписки</b>\n\n"
        "💰 Стоимость: 999 ₽/месяц\n"
        "✅ 3 анализа + 200 сообщений",
        reply_markup=keyboard,
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
        "/renew - Продлить подписку\n"
        "/help - Эта справка\n\n"
        "📞 <b>Поддержка:</b> @support_username",
        parse_mode="HTML"
    )


@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Handle photo uploads."""
    user = await get_or_create_user(message.from_user.id)
    
    if not is_user_active(user):
        await message.answer("❌ У вас нет активной подписки. Используйте /start для оплаты.")
        return
    
    if user.analyses_left <= 0:
        await message.answer("❌ У вас закончились анализы. Используйте /renew для продления.")
        return
    
    current_state = await state.get_state()
    
    # Download photo
    photo = message.photo[-1]  # Get highest resolution
    file = await bot.get_file(photo.file_id)
    photo_bytes = await bot.download_file(file.file_path)
    
    # Validate image quality
    is_valid, error_msg = validate_image_quality(photo_bytes)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    
    if current_state is None:
        # First photo - should be front
        is_valid, error_msg = validate_front_photo(photo_bytes)
        if not is_valid:
            await message.answer(f"❌ {error_msg}")
            return
        
        # Save front photo and wait for profile
        await state.update_data(front_file_id=photo.file_id)
        await state.set_state(PhotoStates.waiting_profile)
        
        await message.answer(
            "✅ Фото анфас принято!\n\n"
            "📸 <b>Шаг 2/2: Профиль</b>\n"
            "Отправьте фото в профиль (боком к камере)"
        )
    
    elif current_state == PhotoStates.waiting_profile:
        # Second photo - should be profile
        is_valid, error_msg = validate_profile_photo(photo_bytes)
        if not is_valid:
            await message.answer(f"❌ {error_msg}")
            return
        
        # Get front photo file_id
        data = await state.get_data()
        front_file_id = data.get("front_file_id")
        
        if not front_file_id:
            await message.answer("❌ Ошибка: не найдено фото анфас. Начните заново.")
            await state.clear()
            return
        
        # Create session
        async for db_session in get_session():
            session = Session(
                user_id=user.id,
                front_file_id=front_file_id,
                profile_file_id=photo.file_id,
                status=SessionStatus.PENDING
            )
            db_session.add(session)
            await db_session.commit()
            await db_session.refresh(session)
            
            # Enqueue for processing
            await task_queue.enqueue(session.id)
            
            # Update user quotas
            user.analyses_left -= 1
            await db_session.commit()
        
        await state.clear()
        
        await message.answer(
            "✅ Оба фото получены!\n\n"
            "⏳ Анализ запущен... Это займёт 1-2 минуты\n"
            "🔬 Обрабатываем ваши фото с помощью ИИ\n\n"
            "Результат придёт автоматически!"
        )
        
        # Start checking for results
        asyncio.create_task(check_session_result(message.from_user.id, session.id))


async def check_session_result(user_id: int, session_id: int):
    """Check session result and send when ready."""
    max_attempts = 60  # 5 minutes max
    attempt = 0
    
    while attempt < max_attempts:
        await asyncio.sleep(5)  # Check every 5 seconds
        attempt += 1
        
        async for db_session in get_session():
            session = await db_session.get(Session, session_id)
            
            if session.status == SessionStatus.DONE and session.result_json:
                # Send results
                report = session.result_json.get("report", "Отчёт не найден")
                metrics = session.result_json.get("metrics", {})
                
                await bot.send_message(
                    user_id,
                    f"🎉 <b>Анализ готов!</b>\n\n{report}",
                    parse_mode="HTML"
                )
                return
            
            elif session.status == SessionStatus.FAILED:
                await bot.send_message(
                    user_id,
                    "❌ Произошла ошибка при анализе. Попробуйте ещё раз или обратитесь в поддержку."
                )
                return
    
    # Timeout
    await bot.send_message(
        user_id,
        "⏰ Анализ занимает больше времени, чем обычно. Результат придёт позже."
    )


@dp.message(F.text)
async def handle_text(message: Message):
    """Handle text messages (Q&A)."""
    user = await get_or_create_user(message.from_user.id)
    
    if not is_user_active(user):
        await message.answer("❌ У вас нет активной подписки. Используйте /start для оплаты.")
        return
    
    if user.messages_left <= 0:
        await message.answer("❌ У вас закончились сообщения. Используйте /renew для продления.")
        return
    
    # Simple echo for now - implement proper Q&A later
    await message.answer(
        "💬 Функция Q&A будет доступна после завершения анализа.\n"
        "Пока что отправьте два фото для анализа!"
    )


async def payment_webhook_handler(request):
    """Handle YooKassa payment webhooks."""
    try:
        body = await request.read()
        headers = dict(request.headers)
        
        # Verify signature
        if not payment_manager.verify_webhook_signature(body, headers):
            return web.Response(status=400, text="Invalid signature")
        
        # Process webhook
        notification_data = await request.json()
        result = payment_manager.process_webhook(notification_data)
        
        if result:
            user_id = result["user_id"]
            
            # Update user subscription
            async for db_session in get_session():
                user = await db_session.get(User, user_id)
                if user:
                    user.is_active_until = datetime.utcnow() + timedelta(days=30)
                    user.analyses_left = 3
                    user.messages_left = 200
                    await db_session.commit()
                    
                    # Notify user
                    await bot.send_message(
                        user_id,
                        "🎉 <b>Подписка активирована!</b>\n\n"
                        "✅ 3 анализа\n"
                        "✅ 200 сообщений\n"
                        "✅ 30 дней доступа\n\n"
                        "Отправьте два фото для начала анализа!",
                        parse_mode="HTML"
                    )
        
        return web.Response(status=200, text="OK")
        
    except Exception as e:
        logger.error(f"Payment webhook error: {e}")
        return web.Response(status=500, text="Internal error")


async def on_startup():
    """Initialize bot on startup."""
    logger.info("Starting HD | Lookism bot...")
    
    # Initialize database
    await create_db_and_tables()
    
    # Initialize queue
    await init_queue()
    
    # Set webhook if URL provided
    if WEBHOOK_URL:
        await bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")
        logger.info(f"Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")
    
    logger.info("Bot started successfully!")


async def on_shutdown():
    """Cleanup on shutdown."""
    logger.info("Shutting down bot...")
    await bot.session.close()
    await task_queue.disconnect()


def create_app():
    """Create web application."""
    app = web.Application()
    
    # Add payment webhook route
    app.router.add_post(PAYMENT_WEBHOOK_PATH, payment_webhook_handler)
    
    # Setup bot webhook
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    
    setup_application(app, dp, bot=bot)
    
    return app


async def main():
    """Main entry point."""
    if WEBHOOK_URL:
        # Run with webhook (for production)
        app = create_app()
        
        # Setup startup/shutdown
        app.on_startup.append(lambda app: asyncio.create_task(on_startup()))
        app.on_shutdown.append(lambda app: asyncio.create_task(on_shutdown()))
        
        # Run web server
        web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    else:
        # Run with polling (for development)
        await on_startup()
        
        try:
            await dp.start_polling(bot)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        finally:
            await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
