import hmac
import hashlib
import json
from dotenv import load_dotenv

# --- Загрузка .env должна быть в самом начале ---
load_dotenv()

import asyncio
import logging
import os
from datetime import datetime, timezone
import sys

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from yookassa.domain.notification import WebhookNotification

from core.scheduler import setup_scheduler
from core.webhooks import yookassa_webhook_handler

# --- Импорт модулей проекта ---
from core.payments import create_yookassa_payment
from database import (
    create_db_and_tables, add_user, check_subscription, 
    give_subscription_to_user, get_user, decrement_user_messages, decrement_user_analyses
)
from core.validators import validate_and_analyze_photo
from core.report_logic import generate_report_text
from core.integrations.deepseek import get_ai_answer
from core.utils import split_long_message

# --- Состояния FSM ---
class ChatStates(StatesGroup):
    getting_front_photo = State()
    getting_profile_photo = State()
    chatting = State()

# --- Логирование --- #
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)

# --- Конфигурация --- #
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()]
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")

WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", 8080))
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL")

TELEGRAM_WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}'
YOOKASSA_WEBHOOK_PATH = os.getenv("YOOKASSA_WEBHOOK_PATH", "/yookassa/webhook")

if not BOT_TOKEN:
    raise ValueError("Токен бота не найден. Проверьте .env файл.")

dp = Dispatcher()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# --- Клавиатуры --- #
def escape_html(text: str) -> str:
    """Escapes characters for Telegram HTML parsing."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def get_main_keyboard(is_admin_user: bool):
    buttons = [
        [InlineKeyboardButton(text="📸 Начать анализ", callback_data="start_analysis")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile")],
        [InlineKeyboardButton(text="💬 Чат с ИИ", callback_data="chat_with_ai")]
    ]
    if is_admin_user:
        buttons.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payment_keyboard(payment_url: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)]
    ])

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# --- Обработчики команд --- #
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    user_id = message.from_user.id
    logger.info(f"🚀 Пользователь {user_id} нажал /start")
    await add_user(user_id)
    
    is_admin_user = is_admin(user_id)
    has_subscription = await check_subscription(user_id)

    if is_admin_user:
        await message.answer("👑 Добро пожаловать, Администратор!", reply_markup=get_main_keyboard(True))
        return

    if has_subscription:
        user = await get_user(user_id)
        await message.answer(
            f"Добро пожаловать! У вас активная подписка до {user.is_active_until.strftime('%d.%m.%Y')}.\n"
            f"Анализов осталось: {user.analyses_left}\n"
            f"Сообщений осталось: {user.messages_left}",
            reply_markup=get_main_keyboard(False)
        )
    else:
        await message.answer(
            "Привет, я ND | Lookism — твой персональный ментор в мире люксмаксинга.\n\n" 
            "Немного того, что я умею:\n" 
            "— анализирую анфас + профиль (углы, симметрия, skin и т.д.)\n" 
            "— ставлю рейтинг Sub-5 → PSL-God с конкретным планом\n" 
            "— отвечаю на все вопросы с учетом твоих метрик\n\n" 
            "Я не обычный искусственный интеллект. ND был разработан и запрограммирован специально под улучшение качество жизни. И всё, что ты услышишь от меня, это рабочие и проверенные исследованиями данные.\n" 
            "Теперь ты можешь смело забыть про коуп методы, гайды с откатами, не долгосрочные результаты."
        )
        await process_payment_start(message)

@dp.callback_query(F.data == "subscribe")
async def process_payment_callback(cq: CallbackQuery):
    await process_payment_start(cq.message)

async def process_payment_start(message: types.Message):
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="💰 ОПЛАТИТЬ", callback_data="pay"))
    await message.answer(
        "📜 Подписка: 990Р / месяц\n"
        "Включает 3 полных анализа и 200 сообщений-консультаций.\n\n"
        "💲 Нажми кнопку ОПЛАТИТЬ, чтобы активировать доступ.",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data == "pay")
async def pay_button_callback(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    payment = create_yookassa_payment(user_id=user_id, amount="5.00", bot_username=bot_username)
    if payment:
        await callback.message.answer(
            "Ваша ссылка на оплату готова. Нажмите на кнопку ниже, чтобы перейти к оплате.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment.confirmation.confirmation_url)]
            ])
        )
    else:
        await callback.message.answer("Не удалось создать ссылку на оплату. Попробуйте позже.")
    await callback.answer()

@dp.callback_query(F.data == "start_analysis")
async def start_analysis(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = await get_user(user_id)

    if is_admin(user_id):
        await state.set_state(ChatStates.getting_front_photo)
        await callback.message.answer("Пожалуйста, загрузите фото анфас.")
        await callback.answer()
        return

    has_subscription = await check_subscription(user_id)

    # Проверка, есть ли у пользователя активная подписка
    if not has_subscription:
        await callback.answer("Для доступа к анализу необходима активная подписка.", show_alert=True)
        return

    if user.analyses_left <= 0:
        await callback.answer("У вас закончились анализы. Они обновятся с новой подпиской.", show_alert=True)
        return

    await state.set_state(ChatStates.getting_front_photo)
    await callback.message.answer("Пожалуйста, загрузите фото анфас.")
    await callback.answer()

@dp.callback_query(F.data == "show_profile")
async def show_profile(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if user and user.is_active_until and user.is_active_until > datetime.utcnow():
        days_left = (user.is_active_until - datetime.utcnow()).days
        profile_text = (
            f"👤 **Ваш профиль:**\n\n"
            f"Подписка активна до: **{user.is_active_until.strftime('%d.%m.%Y')}**\n"
            f"Осталось дней: **{days_left}**\n\n"
            f"Анализов доступно: **{user.analyses_left}**\n"
            f"Сообщений доступно: **{user.messages_left}**"
        )
        await callback.message.answer(profile_text)
    else:
        await callback.message.answer("У вас нет активной подписки.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐️ Оформить подписку", callback_data="pay")]
        ]))
    await callback.answer()

# --- Обработка фото ---
@dp.message(ChatStates.getting_front_photo, F.photo)
async def handle_front_photo(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    logger.info(f"Получено фото анфас от user_id: {user_id}")

    success, result_or_error = await validate_and_analyze_photo(message, bot, is_front=True)

    if success:
        await state.update_data(front_photo_data=result_or_error)
        await message.answer("✅ Фото анфас принято. Теперь, пожалуйста, отправьте фото в профиль (вид сбоку).")
        await state.set_state(ChatStates.getting_profile_photo)
    else:
        await message.answer(f"❌ Ошибка: {result_or_error}")


@dp.message(ChatStates.getting_profile_photo, F.photo)
async def handle_profile_photo(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    logger.info(f"Получено фото профиля от user_id: {user_id}")

    success, result_or_error = await validate_and_analyze_photo(message, bot, is_front=False)

    if success:
        logger.info(f"Профильное фото от {user_id} прошло валидацию.")
        await state.update_data(profile_photo_analysis=result_or_error)

        user_data = await state.get_data()
        front_analysis_data = user_data.get('front_photo_data', {})
        profile_analysis_data = user_data.get('profile_photo_analysis', {})

        # Объединяем данные для передачи в run_analysis
        # Убедимся, что передаем полные данные, полученные от Face++
        merged_data = {
            'front_photo_data': front_analysis_data,
            'profile_photo_data': profile_analysis_data
        }
        
        await run_analysis(user_id, state, bot, merged_data)

    else:
        await message.answer(f"❌ Ошибка: {result_or_error}")


async def run_analysis(user_id: int, state: FSMContext, bot: Bot, analysis_data: dict):
    await bot.send_message(user_id, "✅ Все фото приняты. Начинаю анализ... Это может занять несколько минут.")
    try:
        report_text = await generate_report_text(analysis_data)

        # Сохраняем отчет в контекст для будущего чата
        await state.update_data(last_report=report_text)

        message_parts = split_long_message(report_text)
        for i, part in enumerate(message_parts):
            await bot.send_message(user_id, part) # Отключаем Markdown
            if i < len(message_parts) - 1:
                await asyncio.sleep(0.5)

        follow_up_message = """
В анализе и плане улучшения я мог расписать что-то пока что непонятными для тебя словами. Если ты не знаешь, как делать тот или иной метод - спроси. Я и мой ИИ с луксмаксерской базой данных ответим тебе на любые вопросы и поможем тебе стать красивее.

А если ты захочешь сделать новый анализ своих фото и проверить, поменялся ли ты, введи команду /analyze, чтобы запустить повторный анализ.
"""
        await bot.send_message(user_id, follow_up_message)

        await state.set_state(ChatStates.chatting)
        logger.info(f"Пользователь {user_id} вошел в режим чата после получения отчета.")

    except Exception as e:
        logger.error(f"Критическая ошибка в run_analysis для user_id {user_id}: {e}", exc_info=True)
        await bot.send_message(user_id, "Произошла критическая ошибка при создании отчета. Пожалуйста, попробуйте позже.")
        await state.clear() # Очищаем состояние только в случае критической ошибки

# --- Чат с ИИ ---
@dp.callback_query(F.data == "chat_with_ai")
async def chat_with_ai_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not is_admin(user_id) and (not user or not user.is_active_until or user.is_active_until < datetime.utcnow()):
        await callback.answer("Доступ к чату есть только при активной подписке.", show_alert=True)
        return
    
    await state.set_state(ChatStates.chatting)
    await callback.message.answer("Вы перешли в режим чата. Напишите ваше сообщение.")
    await callback.answer()

@dp.message(ChatStates.chatting, F.text)
async def handle_text_in_chat_mode(message: Message, state: FSMContext):
    """Обрабатывает текстовые сообщения в режиме чата с ИИ."""
    user_id = message.from_user.id
    user_question = message.text
    logger.info(f"Пользователь {user_id} в режиме чата спрашивает: '{user_question}'")

    temp_message = await message.answer("🤖 Думаю над ответом...")

    try:
        user_data = await state.get_data()
        last_report = user_data.get('last_report', 'Контекст предыдущего анализа отсутствует.')
        chat_history = user_data.get('chat_history', [])

        # Добавляем текущий вопрос в историю
        chat_history.append({"role": "user", "content": user_question})

        system_prompt = f"""Ты — элитный AI-аналитик 'HD | Lookism'. Ты продолжаешь диалог с пользователем после предоставления ему детального отчета о внешности. Твоя задача — отвечать на его вопросы, давать пояснения и дополнительные советы. Будь профессионален, используй lookmaxxing-терминологию, но оставайся поддерживающим и полезным.

Вот предыдущий отчет для контекста:
{last_report}
"""

        # Формируем промпт из истории сообщений
        # Мы передаем последние несколько сообщений, чтобы не превышать лимит токенов
        history_for_prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in chat_history[-10:]])

        ai_response = await get_ai_answer(system_prompt, history_for_prompt)

        # Добавляем ответ ИИ в историю
        chat_history.append({"role": "assistant", "content": ai_response})
        await state.update_data(chat_history=chat_history)

        await temp_message.edit_text(ai_response)

    except Exception as e:
        logger.error(f"Ошибка в режиме чата для user_id {user_id}: {e}", exc_info=True)
        await temp_message.edit_text("Произошла ошибка при обработке вашего вопроса. Попробуйте еще раз.")

# --- Запуск бота в режиме Webhook --- #
async def on_startup(bot: Bot):
    """Выполняется при старте бота."""
    # Убедитесь, что BASE_WEBHOOK_URL и YOOKASSA_WEBHOOK_PATH определены в .env и загружены
    webhook_url = f"{BASE_WEBHOOK_URL}{YOOKASSA_WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info(f"Вебхук установлен на: {webhook_url}")

async def on_shutdown(bot: Bot):
    """Выполняется при остановке бота."""
    logger.info("Остановка бота и удаление вебхука...")
    await bot.delete_webhook()

async def main_webhook():
    """Основная функция для запуска бота и веб-сервера."""
    await create_db_and_tables()

    # Регистрируем on_startup и on_shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Создаем приложение aiohttp
    app = web.Application()
    app['bot'] = bot

    # Регистрируем обработчик для YooKassa
    app.router.add_post(YOOKASSA_WEBHOOK_PATH, yookassa_webhook_handler)

    # Запускаем веб-сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start()

    logger.info(f"Сервер запущен на http://{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")

    # Бесконечный цикл для работы сервера
    await asyncio.Event().wait()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main_webhook())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
