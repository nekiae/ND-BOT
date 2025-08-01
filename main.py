import hmac
import hashlib
import json
import os
from dotenv import load_dotenv

# --- Загрузка .env должна быть в самом начале ---
load_dotenv()

# --- Загрузка настроек из .env ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH")
YOOKASSA_WEBHOOK_PATH = os.getenv("YOOKASSA_WEBHOOK_PATH")
WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", 8080)))
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(',') if admin_id]

import asyncio
from contextlib import suppress
import logging
from datetime import datetime, timezone
import sys

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, CommandObject, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand
from aiogram.filters import BaseFilter

from core.states import AdminStates, AdminAmbassador, IsAdminFilter, AnalysisStates, ChatStates
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message,
    CallbackQuery,
    InputFile, FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from yookassa.domain.notification import WebhookNotification



from core.scheduler import setup_scheduler
from core.webhooks import yookassa_webhook_handler
from admin_handlers import admin_router

# --- Импорт модулей проекта ---
from core.payments import create_yookassa_payment
from database import (
    create_db_and_tables, add_user, check_subscription, 
    give_subscription_to_user, get_user, decrement_user_analyses, decrement_user_messages,
    get_bot_statistics, get_subscription_stats, get_pending_payouts_count,
    get_user_detailed_stats, get_user_by_username, revoke_subscription, get_all_users,
    get_all_ambassadors, get_referral_stats, set_ambassador_status, confirm_referral_payouts
)

from core.report_logic import generate_report_text
from core.integrations.deepseek import get_deepseek_response
from core.utils import split_long_message, sanitize_html_for_telegram
from core.validators import detect_face, check_head_pose, is_bright_enough
import redis.asyncio as redis

# --- Состояния FSM ---

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
WEB_SERVER_PORT = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", 8080)))
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL")

# Используем статический путь без токена, чтобы избежать проблем с символом ':'
TELEGRAM_WEBHOOK_PATH = '/webhook'
YOOKASSA_WEBHOOK_PATH = os.getenv("YOOKASSA_WEBHOOK_PATH", "/yookassa/webhook")

if not BOT_TOKEN:
    raise ValueError("Токен бота не найден. Проверьте .env файл.")

dp = Dispatcher()

# Регистрируем админ-роутер в первую очередь, чтобы его хендлеры имели приоритет
dp.include_router(admin_router)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost"))

# --- Клавиатуры --- #
def escape_html(text: str) -> str:
    """Escapes characters for Telegram HTML parsing."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def get_main_keyboard(is_admin_user: bool):
    buttons = [
        [InlineKeyboardButton(text="📸 Начать анализ", callback_data="start_analysis")],
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

@dp.callback_query(F.data == "show_profile")
async def show_profile(callback: types.CallbackQuery, bot: Bot):
    """Shows the user's profile with subscription and referral stats."""
    user_id = callback.from_user.id
    user = await get_user(user_id)

    if not user or not user.is_active_until or user.is_active_until < datetime.now(timezone.utc):
        await callback.answer("У вас нет активной подписки.", show_alert=True)
        return

    response_text = (
        f"<b>👤 Ваш профиль</b>\n\n"
        f"Подписка активна до: {user.is_active_until.strftime('%d.%m.%Y')}\n"
        f"Анализов осталось: {user.analyses_left}\n"
        f"Сообщений осталось: {user.messages_left}"
    )

    if user.is_ambassador:
        stats = await get_referral_stats(user.id)
        bot_user = await bot.get_me()
        referral_link = f"https://t.me/{bot_user.username}?start=ref{user.id}"
        
        response_text += (
            f"\n\n<b>👑 Статус Амбассадора</b>\n"
            f"Ваша реферальная ссылка:\n<code>{referral_link}</code>\n\n"
            f"<b>Статистика:</b>\n"
            f"  - Всего оплативших: {stats['total_paid_referrals']}\n"
            f"  - Ожидают выплаты: {stats['pending_payouts']}"
        )

    await callback.message.answer(response_text, disable_web_page_preview=True)
    await callback.answer()


# --- Обработчики команд --- #
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot, command: CommandObject):
    await state.clear()
    user_id = message.from_user.id
    # Parse referral code from the start command
    referred_by_id = None
    if command.args and command.args.startswith('ref'):
        try:
            ref_id_str = command.args[3:]
            if ref_id_str.isdigit():
                referred_by_id = int(ref_id_str)
                logger.info(f"User {user_id} was referred by {referred_by_id}")
            else:
                logger.warning(f"Invalid referral code format: {command.args}")
        except (ValueError, TypeError):
            logger.warning(f"Could not parse referral code: {command.args}")

    logger.info(f"🚀 Пользователь {user_id} нажал /start")
    await add_user(user_id, message.from_user.username, referred_by_id=referred_by_id)
    
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
            "👋 Привет, я ND | Lookism — твой персональный ментор в мире люксмаксинга.\n\n" 
            "Немного того, что я умею:\n" 
            "— анализирую анфас + профиль (углы, симметрия, skin и т.д.)\n" 
            "— ставлю рейтинг Sub-5 → PSL-God с конкретным планом\n" 
            "— отвечаю на все вопросы с учетом твоих метрик\n\n" 
            "Я не обычный искусственный интеллект. ND был разработан и запрограммирован специально под улучшение качество жизни. И всё, что ты услышишь от меня, это рабочие и проверенные исследованиями данные.\n" 
            "Теперь ты можешь смело забыть про коуп методы, гайды с откатами, не долгосрочные результаты.\n\n"
            "🎯 Будь с нами:\n"
            "https://t.me/deltagood"
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
        "Включает 2 полных анализа и 200 сообщений-консультаций.\n\n"
        "💲 Нажми кнопку ОПЛАТИТЬ, чтобы активировать доступ.",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data == "pay")
async def pay_button_callback(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    payment = create_yookassa_payment(user_id=user_id, amount="990.00", bot_username=bot_username)
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

async def begin_analysis_flow(message_or_cq: types.Message | types.CallbackQuery, state: FSMContext, bot: Bot):
    """Unified logic to start the analysis flow, checking subscription and limits."""
    user_id = message_or_cq.from_user.id
    bot_user = await bot.get_me()
    bot_username = bot_user.username

    if isinstance(message_or_cq, types.Message):
        chat_id = message_or_cq.chat.id
        responder = message_or_cq
    else:  # CallbackQuery
        chat_id = message_or_cq.message.chat.id
        responder = message_or_cq.message

    if not is_admin(user_id):
        if not await check_subscription(user_id):
            payment = create_yookassa_payment(user_id, amount="999.00", bot_username=bot_username)
            keyboard = get_payment_keyboard(payment.confirmation.confirmation_url)
            await responder.answer("Для доступа к анализу необходима активная подписка.", reply_markup=keyboard)
            return

        user = await get_user(user_id)
        if user and user.analyses_left <= 0:
            payment = create_yookassa_payment(user_id, amount="999.00", bot_username=bot_username)
            keyboard = get_payment_keyboard(payment.confirmation.confirmation_url)
            await responder.answer("У вас закончились доступные анализы. Чтобы получить новые, оформите подписку.", reply_markup=keyboard)
            return

    # Proceed with analysis flow
    await state.set_state(AnalysisStates.awaiting_front_photo)
    await bot.send_photo(
        chat_id=chat_id,
        photo=FSInputFile("photo/front.jpg"),
        caption=(
            "📸 <b>ШАГ 1 / 2 — Фото анфас</b>\n\n"
            "Пример выше.\n\n"
            "1. Камера на уровне глаз, лицо прямо.\n"
            "2. Ровный свет, без резких теней.\n"
            "3. Без макияжа, фильтров, очков.\n\n"
            "<b>Отправьте ваше фото в ответ.</b>"
        ),
        parse_mode=ParseMode.HTML
    )
    if isinstance(message_or_cq, types.CallbackQuery):
        await message_or_cq.answer()

@dp.callback_query(F.data == "start_analysis")
async def start_analysis_callback(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await begin_analysis_flow(callback, state, bot)

@dp.message(Command("analyze"), StateFilter("*"))
async def analyze_command_handler(message: types.Message, state: FSMContext, bot: Bot):
    """Handles the /analyze command by calling the unified analysis flow."""
    await begin_analysis_flow(message, state, bot)


@dp.message(Command("stats"), StateFilter("*"))
async def stats_command_handler(message: types.Message, bot: Bot):
    """Handles the /stats command and shows user's subscription info."""
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user or not user.is_active_until or user.is_active_until < datetime.now(timezone.utc):
        await message.answer("У вас нет активной подписки. Нажмите /start, чтобы узнать больше.")
        return

    response_text = (
        f"<b>📊 Ваша статистика</b>\n\n"
        f"Подписка активна до: {user.is_active_until.strftime('%d.%m.%Y')}\n"
        f"Анализов осталось: {user.analyses_left}\n"
        f"Сообщений осталось: {user.messages_left}"
    )

    # Если пользователь является амбассадором, добавляем реферальную статистику
    if user.is_ambassador:
        bot_user = await bot.get_me()
        stats = await get_referral_stats(user.id)
        referral_link = f"https://t.me/{bot_user.username}?start=ref{user.id}"
        
        response_text += (
            f"\n\n<b>👑 Статус Амбассадора</b>\n"
            f"Ваша реферальная ссылка:\n<code>{referral_link}</code>\n\n"
            f"<b>Статистика:</b>\n"
            f"  - Всего переходов: {stats['total_referred']}\n"
            f"  - Всего оплативших: {stats['total_paid_referrals']}\n"
            f"  - Ожидают выплаты: {stats['pending_payouts']}"
        )

    await message.answer(response_text, disable_web_page_preview=True)

@dp.message(AnalysisStates.awaiting_front_photo, F.photo)
async def handle_front_photo(message: Message, state: FSMContext, bot: Bot):
    """Validates the front photo and asks for the profile photo."""
    file_info = await bot.get_file(message.photo[-1].file_id)
    photo_bytes = (await bot.download_file(file_info.file_path)).read()

    # 1. Проверка яркости
    if not is_bright_enough(photo_bytes):
        await message.answer("❌ <b>Слишком темное фото.</b>\n\nПожалуйста, сделайте фото при хорошем, равномерном освещении.")
        return

    # 2. Проверка лица и ракурса через Face++
    face_data = await detect_face(photo_bytes)

    if not face_data or "faces" not in face_data or not face_data["faces"]:
        error_msg = face_data.get("error_message", "Не удалось распознать лицо на фото. Попробуйте другое изображение.")
        await message.answer(f"❌ <b>Лицо не найдено.</b>\n\n{error_msg}")
        return

    if len(face_data["faces"]) > 1:
        await message.answer("❌ <b>Слишком много лиц.</b>\n\nПожалуйста, загрузите фото, где в кадре только один человек.")
        return

    yaw_angle = face_data['faces'][0]['attributes']['headpose']['yaw_angle']
    is_valid, error_message = check_head_pose(yaw_angle, is_front=True)

    if not is_valid:
        await message.answer(error_message, parse_mode=ParseMode.HTML)
        return

    # Все проверки пройдены
    await state.update_data(front_photo_id=message.photo[-1].file_id)
    await state.set_state(AnalysisStates.awaiting_profile_photo)
    
    await bot.send_photo(
        chat_id=message.chat.id,
        photo=FSInputFile("photo/profile.jpg"),
        caption=(
            "✅ <b>Фото анфас принято!</b>\n\n"
            "📸 <b>ШАГ 2 / 2 — Фото профиля</b>\n\n"
            "Пример выше.\n\n"
            "Теперь загрузите <b>фото профиля</b> — строгий боковой вид.\n"
            "Требования те же: ровный свет, без фильтров и ретуши."
        ),
        parse_mode=ParseMode.HTML
    )

@dp.message(AnalysisStates.awaiting_profile_photo, F.photo)
async def handle_profile_photo(message: Message, state: FSMContext, bot: Bot):
    """Validates the profile photo and queues the analysis task."""
    file_info = await bot.get_file(message.photo[-1].file_id)
    photo_bytes = (await bot.download_file(file_info.file_path)).read()

    # 1. Проверка яркости
    if not is_bright_enough(photo_bytes):
        await message.answer("❌ <b>Слишком темное фото.</b>\n\nПожалуйста, сделайте фото при хорошем, равномерном освещении.")
        return

    # 2. Проверка лица и ракурса
    face_data = await detect_face(photo_bytes)

    if not face_data or "faces" not in face_data or not face_data["faces"]:
        error_msg = face_data.get("error_message", "Не удалось распознать лицо на фото. Попробуйте другое изображение.")
        await message.answer(f"❌ <b>Лицо не найдено.</b>\n\n{error_msg}")
        return

    if len(face_data["faces"]) > 1:
        await message.answer("❌ <b>Слишком много лиц.</b>\n\nПожалуйста, загрузите фото, где в кадре только один человек.")
        return

    yaw_angle = face_data['faces'][0]['attributes']['headpose']['yaw_angle']
    is_valid, error_message = check_head_pose(yaw_angle, is_front=False)

    if not is_valid:
        await message.answer(error_message, parse_mode=ParseMode.HTML)
        return

    # Все проверки пройдены
    user_data = await state.get_data()
    front_photo_id = user_data.get('front_photo_id')
    profile_photo_id = message.photo[-1].file_id

    await queue_analysis_task(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        front_photo_id=front_photo_id,
        profile_photo_id=profile_photo_id
    )
    
    await message.answer("✅ <b>Отлично!</b>\n\nВаши фотографии приняты и отправлены на анализ. Ожидайте, это может занять несколько минут.")
    await state.clear()

async def queue_analysis_task(user_id: int, chat_id: int, front_photo_id: str, profile_photo_id: str):
    """Queues the analysis task and decrements the user's analysis count."""
    task_data = {
        "user_id": user_id,
        "chat_id": chat_id,
        "front_photo_id": front_photo_id,
        "profile_photo_id": profile_photo_id
    }
    try:
        # Проверяем, остались ли у пользователя анализы
        if not is_admin(user_id):
            user = await get_user(user_id)
            if not user or user.analyses_left <= 0:
                bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                await bot.send_message(chat_id, "У вас закончились анализы. Оформите подписку, чтобы получить новые.")
                return

        await redis_client.lpush("analysis_queue", json.dumps(task_data))
        logger.info(f"Task for user {user_id} has been added to the queue.")

    except Exception as e:
        logger.error(f"Failed to queue analysis task for user {user_id}: {e}")
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        await bot.send_message(chat_id, "Не удалось поставить задачу в очередь. Пожалуйста, попробуйте позже.")





# Должен срабатывать только когда нет активного FSM состояния (None) или пользователь в обычном чате
@dp.message(F.text, StateFilter(None, ChatStates.chatting))
async def handle_all_text(message: types.Message, state: FSMContext, bot: Bot):
    # Explicitly ignore commands to let their handlers process them
    if message.text.startswith('/'):
        return
    """Handles all text messages, acting as a chatbot, if the user is not in another process."""
    current_state = await state.get_state()
    if current_state in [AnalysisStates.awaiting_front_photo, AnalysisStates.awaiting_profile_photo]:
        # If the user is in the analysis process, ignore text messages.
        return

    user_id = message.from_user.id
    user_info = await get_user(user_id)
    has_subscription = await check_subscription(user_id)

    # Check if user has a subscription or is an admin
    if not has_subscription and not is_admin(user_id):
        await message.answer("Для общения с ND нужна активная подписка.")
        return

    # Check if user has messages left
    if not is_admin(user_id) and ((not user_info) or user_info.messages_left <= 0):
        await message.answer("У вас закончились сообщения для чата с ND.")
        return

    # Get chat history from FSM or initialize it
    data = await state.get_data()
    chat_history = data.get('chat_history', [])
    user_question = message.text

    # --- Prepare context for the AI ---
    system_prompt_addendum = ""
    if user_info and user_info.last_analysis_metrics:
        try:
            # Округляем числовые значения для компактности
            metrics_to_show = {k: round(v, 2) if isinstance(v, (int, float)) else v for k, v in user_info.last_analysis_metrics.items()}
            metrics_str = json.dumps(metrics_to_show, ensure_ascii=False, indent=2)
            system_prompt_addendum = f"\n\n### Контекст последнего анализа пользователя:\n{metrics_str}"
        except (TypeError, json.JSONDecodeError):
            logger.warning(f"Could not serialize last_analysis_metrics for user {user_id}")

    sent_message = await message.answer("ND печатает...")

    try:
        full_response = ""
        last_sent_text = ""
        update_task = None
        lock = asyncio.Lock()

        # This task will periodically update the message in Telegram
        async def message_updater():
            nonlocal last_sent_text
            while True:
                await asyncio.sleep(1.5)  # Update every 1.5 seconds
                async with lock:
                    current_text = full_response
                if current_text and current_text != last_sent_text:
                    with suppress(TelegramBadRequest): # Ignore "message is not modified" errors
                        await sent_message.edit_text(current_text + "▌") # Add cursor
                    last_sent_text = current_text

        update_task = asyncio.create_task(message_updater())

        # Stream response from the AI, including the new context
        async for chunk in get_deepseek_response(user_question, chat_history, system_prompt_addendum=system_prompt_addendum):
            async with lock:
                full_response += chunk

        # Stop the updater task once streaming is complete
        if update_task:
            update_task.cancel()
            with suppress(asyncio.CancelledError):
                await update_task

        # Send the final, complete message without the cursor
        if full_response:
            sanitized_response = sanitize_html_for_telegram(full_response)
            try:
                await sent_message.edit_text(sanitized_response, parse_mode=ParseMode.HTML)
            except TelegramBadRequest:
                await sent_message.edit_text(full_response) # Fallback
        else:
            await sent_message.edit_text("Не удалось получить ответ. Попробуйте позже.")

        # Update chat history and decrement messages
        if not is_admin(user_id):
            await decrement_user_messages(user_id)
        
        chat_history.append({"role": "user", "content": user_question})
        chat_history.append({"role": "assistant", "content": full_response})
        # Limit history to the last 40 messages to avoid large context
        if len(chat_history) > 40:
            chat_history = chat_history[-40:]
        await state.update_data(chat_history=chat_history)

    except Exception as e:
        logger.error(f"Error processing text message for user {user_id}: {e}", exc_info=True)
        if 'update_task' in locals() and update_task and not update_task.done():
            update_task.cancel()
        await sent_message.edit_text("Произошла ошибка при обработке вашего запроса.")


# --- Запуск бота в режиме Webhook --- #

# --- Запуск бота в режиме Webhook --- #
async def set_main_menu(bot: Bot):
    """Создает меню с командами в интерфейсе Telegram."""
    main_menu_commands = [
        BotCommand(command='/start', description='🚀 Перезапустить бота'),
        BotCommand(command='/analyze', description='💡 Новый анализ'),
        BotCommand(command='/stats', description='📊 Моя статистика')
    ]
    await bot.set_my_commands(main_menu_commands)




async def on_startup(bot: Bot):
    """Выполняется при старте бота."""
    await set_main_menu(bot)
    # Устанавливаем вебхук для Telegram на правильный путь
    # Безопасно обрезаем пробелы и слэш на конце у BASE_WEBHOOK_URL
    clean_base = (BASE_WEBHOOK_URL or "").strip().rstrip("/")
    webhook_url = f"{clean_base}{TELEGRAM_WEBHOOK_PATH}"
    # Разрешаем Telegram присылать нужные типы апдейтов (включая callback_query)
    allowed_updates = [
        "message",
        "callback_query",
        "inline_query",
        "chat_member",
        "my_chat_member"
    ]
    await bot.set_webhook(webhook_url, drop_pending_updates=True, allowed_updates=allowed_updates)
    logger.info(f"Вебхук Telegram установлен на: {webhook_url}")

async def on_shutdown(bot: Bot):
    """Выполняется при остановке бота."""
    logger.info("Остановка бота, удаление вебхука и закрытие соединений...")
    await bot.delete_webhook()
    await redis_client.close()
    logger.info("Соединение с Redis закрыто.")

async def main_webhook():
    """Основная функция для запуска бота и веб-сервера."""
    await create_db_and_tables()

    # Регистрируем on_startup и on_shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Создаем веб-приложение aiohttp
    app = web.Application()

    # Ключевое исправление: передаем бота в контекст сервера, чтобы он был доступен в вебхуках
    app['bot'] = bot

    # Регистрируем обработчики
    # 1. Обработчик для Telegram
    telegram_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    telegram_handler.register(app, path=WEBHOOK_PATH)

    # 2. Обработчик для YooKassa
    app.router.add_post(YOOKASSA_WEBHOOK_PATH, yookassa_webhook_handler)

    # Готовим и запускаем приложение
        # Регистрируем Telegram вебхук-обработчик на универсальный путь (поддерживает любой токен)
    setup_application(app, dp, bot=bot, path=TELEGRAM_WEBHOOK_PATH)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start()

    logger.info(f"Сервер запущен на http://{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")

    # Бесконечный цикл для работы сервера
    await asyncio.Event().wait()

async def main_polling():
    """Запускает бота в режиме опроса (polling) для локальной разработки."""
    logger.info("Запуск бота в режиме опроса...")

    # Убедимся, что таблицы в БД созданы
    await create_db_and_tables()

    # Настраиваем и запускаем планировщик
    scheduler = setup_scheduler(bot)
    scheduler.start()

    # Удаляем вебхук, если он был установлен, и запускаем опрос
    try:
        

        # Start polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await redis_client.aclose()
        logger.info("Соединение с Redis закрыто.")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        # Для локальной разработки используйте main_polling()
        # Для продакшена (с вебхуком) используйте main_webhook()
        run_mode = os.getenv("RUN_MODE", "webhook")
        if run_mode == "webhook":
            asyncio.run(main_webhook())
        else:
            asyncio.run(main_polling())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
