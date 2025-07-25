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
WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", 8080))
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(',') if admin_id]

import asyncio
from contextlib import suppress
import logging
from datetime import datetime, timezone
import sys

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

class AdminStates(StatesGroup):
    GIVE_SUB_USERNAME = State()
    REVOKE_SUB_USERNAME = State()
    BROADCAST_MESSAGE = State() # Состояние для ожидания сообщения для рассылки

from aiogram.types import BotCommand
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message,
    CallbackQuery,
    InputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from yookassa.domain.notification import WebhookNotification

from core.scheduler import setup_scheduler
from core.webhooks import yookassa_webhook_handler

# --- Импорт модулей проекта ---
from core.payments import create_yookassa_payment
from database import (
    create_db_and_tables, add_user, check_subscription, 
    give_subscription_to_user, get_user, decrement_user_analyses, decrement_user_messages,
    get_bot_statistics, get_user_by_username, revoke_subscription, get_all_users
)
from core.validators import validate_and_analyze_photo
from core.report_logic import generate_report_text
from core.integrations.deepseek import get_deepseek_response
from core.utils import split_long_message
import re

# --- Состояния FSM ---
class ChatStates(StatesGroup):
    getting_front_photo = State()
    getting_profile_photo = State()
    chatting = State()  # состояние обычного чата после выдачи отчёта

# --- Логирование --- #
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)

# --- Утилита для безопасного HTML --- #

def sanitize_html_for_telegram(text: str) -> str:
    """Добавляет недостающие закрывающие теги <b> / <i>, чтобы Telegram смог спарсить сообщение."""
    # Конвертируем **bold** и *italic* в HTML, игнорируя маркеры списка
    def bold_repl(match):
        inner = match.group(1)
        if inner.strip().startswith('-'):
            return match.group(0)  # оставляем как есть, это список
        return f"<b>{inner}</b>"

    def italic_repl(match):
        inner = match.group(1)
        if inner.strip().startswith('-'):
            return match.group(0)
        return f"<i>{inner}</i>"

    text = re.sub(r"\*\*(.*?)\*\*", bold_repl, text, flags=re.S)
    text = re.sub(r"(?<!-)\*(?![\s*-])(.*?)\*(?!\S)", italic_repl, text, flags=re.S)

    for tag in ("b", "i"):
        opens = len(re.findall(fr"<{tag}>", text))
        closes = len(re.findall(fr"</{tag}>", text))
        if opens > closes:
            text += "</" + tag + ">" * (opens - closes)
    return text

# --- Конфигурация --- #
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()]
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")

WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", 8080))
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL")

# Используем статический путь без токена, чтобы избежать проблем с символом ':'
TELEGRAM_WEBHOOK_PATH = '/webhook'
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
    await add_user(user_id, message.from_user.username)
    
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
        await callback.message.answer("Пожалуйста, загрузите фото анфас (лицо прямо).")
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
    await callback.message.answer("Пожалуйста, загрузите фото анфас (лицо прямо).")
    await callback.answer()



@dp.message(Command("analyze"), StateFilter("*"))
async def analyze_command_handler(message: types.Message, state: FSMContext):
    """Обрабатывает команду /analyze для запуска нового анализа."""
    user_id = message.from_user.id
    user = await get_user(user_id)

    if is_admin(user_id):
        await state.set_state(ChatStates.getting_front_photo)
        await message.answer("Пожалуйста, загрузите фото анфас (лицо прямо).")
        return

    has_subscription = await check_subscription(user_id)
    if not has_subscription:
        await message.answer("Для доступа к анализу необходима активная подписка.")
        return

    if user.analyses_left <= 0:
        await message.answer("У вас закончились анализы. Они обновятся с новой подпиской.")
        return

    await state.set_state(ChatStates.getting_front_photo)
    await message.answer("Пожалуйста, загрузите фото анфас (лицо прямо).")


@dp.message(Command("stats"), StateFilter("*"))
async def show_stats(message: types.Message):
    """Показывает статистику пользователя: подписка, анализы, сообщения."""
    user = await get_user(message.from_user.id)

    # 1. Проверяем, есть ли пользователь и дата подписки
    if not user or not user.is_active_until:
        await message.answer("У вас нет активной подписки.")
        return

    # 2. Приводим время из БД к UTC, если оно "наивное"
    active_until = user.is_active_until
    if active_until.tzinfo is None:
        active_until = active_until.replace(tzinfo=timezone.utc)

    # 3. Сравниваем с текущим временем в UTC
    if active_until < datetime.now(timezone.utc):
        await message.answer("Срок вашей подписки истек.")
        return

    # 4. Если все в порядке, форматируем и отправляем статистику
    active_until_str = active_until.strftime("%d.%m.%Y %H:%M")

    stats_text = (
        f"<b>📊 Ваша статистика:</b>\n\n"
        f"▪️ <b>Подписка активна до:</b> {active_until_str} (UTC)\n"
        f"▪️ <b>Осталось анализов:</b> {user.analyses_left}\n"
        f"▪️ <b>Осталось сообщений:</b> {user.messages_left}"
    )

    await message.answer(stats_text)


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
        await state.clear()  # Очищаем состояние в случае критической ошибки
        return  # Прерываем дальнейшее выполнение функции, чтобы избежать ошибок



        # --- Новая, надежная логика стриминга ---
        full_response = ""
        update_task = None
        lock = asyncio.Lock()

        async def message_updater():
            # Эта функция будет работать в фоне и обновлять сообщение
            last_sent_text = None
            while True:
                async with lock:
                    current_text = full_response
                
                if current_text and current_text != last_sent_text:
                    with suppress(TelegramBadRequest):
                        await sent_message.edit_text(current_text + " ▌", parse_mode=None)
                        last_sent_text = current_text
                await asyncio.sleep(0.7) # Пауза между обновлениями

        try:
            update_task = asyncio.create_task(message_updater())
            
            response_generator = get_deepseek_response(user_prompt=user_question, chat_history=chat_history)
            async for chunk in response_generator:
                async with lock:
                    full_response += chunk
            
        finally:
            if update_task:
                update_task.cancel()
                with suppress(asyncio.CancelledError):
                    await update_task

        # Финальное обновление без курсора
        html_fixed = sanitize_html_for_telegram(full_response)
        try:
            await sent_message.edit_text(html_fixed, parse_mode=ParseMode.HTML)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                # Финальный текст совпадает с уже отправленным – игнорируем ошибку
                pass
            else:
                await sent_message.edit_text(full_response, parse_mode=None)

        # Обновляем историю чата
        chat_history.append({"role": "user", "content": user_question})
        chat_history.append({"role": "assistant", "content": full_response})
        await state.update_data(chat_history=chat_history)

    except Exception as e:
        logger.error(f"Ошибка в режиме чата для user_id {user_id}: {e}", exc_info=True)
        await temp_message.edit_text("Произошла ошибка при обработке вашего вопроса. Попробуйте еще раз.")

# --- Универсальный обработчик текста (AI) ---

@dp.message(StateFilter(None), F.text)
async def handle_all_text(message: types.Message):
    """Отвечает на любое текстовое сообщение с помощью AI, если пользователь не в другом сценарии."""
    user_id = message.from_user.id
    user = await get_user(user_id)

    # Проверка подписки и лимитов
    if not is_admin(user_id):
        if not user or not user.is_active_until or user.is_active_until < datetime.now(timezone.utc):
            await message.answer("Для общения с ИИ необходима активная подписка.")
            return
        if user.messages_left <= 0:
            await message.answer("У вас закончились сообщения для чата с ИИ. Они обновятся с новой подпиской.")
            return

    user_question = message.text
    logger.info(f"Пользователь {user_id} спрашивает: '{user_question[:50]}...' (универсальный обработчик)")

    temp_message = await message.answer("...")
    sent_message = await temp_message.edit_text("ND генерирует ответ...")

    try:
        full_response = ""
        stream = get_deepseek_response(user_question, chat_history=[])
        
        async for chunk in stream:
            if chunk:
                full_response += chunk
                # Обновляем сообщение не слишком часто, чтобы избежать Rate Limit
                if len(full_response) % 25 == 0:
                    try:
                        await sent_message.edit_text(full_response, parse_mode=None)
                    except Exception:
                        pass # Игнорируем ошибки, если сообщение не изменилось
        
        try:
            html_fixed = sanitize_html_for_telegram(full_response)
            await sent_message.edit_text(html_fixed, parse_mode=ParseMode.HTML)  # Отправляем финальный ответ
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                # Финальный текст совпадает с уже отправленным – игнорируем ошибку
                pass
            else:
                await sent_message.edit_text(full_response, parse_mode=None)

        # Уменьшаем количество сообщений только после успешного ответа
        if not is_admin(user_id):
            await decrement_user_messages(user_id)

    except Exception as e:
        logger.error(f"Ошибка в универсальном AI-обработчике для user_id {user_id}: {e}", exc_info=True)
        await sent_message.edit_text("Произошла ошибка при обработке вашего вопроса. Попробуйте еще раз.")

# --- Новая Админ-панель ---

def get_admin_panel_keyboard():
    """Возвращает клавиатуру для главной панели администратора."""
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="broadcast_start")],
        [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="give_sub_start")],
        [InlineKeyboardButton(text="➖ Отозвать подписку", callback_data="revoke_sub_start")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(F.data == "admin_panel")
async def handle_admin_panel(callback: types.CallbackQuery, state: FSMContext):
    """Показывает главное меню админ-панели и сбрасывает состояние."""
    await state.clear()
    await callback.message.edit_text(
        "👑 <b>Админ-панель</b> 👑",
        reply_markup=get_admin_panel_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def handle_admin_stats(callback: types.CallbackQuery):
    """Показывает статистику бота во всплывающем окне."""
    stats = await get_bot_statistics()
    text = f"📊 Статистика бота:\n- Всего пользователей: {stats['total_users']}\n- Активных подписок: {stats['active_subscriptions']}"
    await callback.answer(text, show_alert=True)

# --- Управление подписками ---
@dp.callback_query(F.data.in_(["give_sub_start", "revoke_sub_start"]))
async def handle_sub_management_start(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает username для управления подпиской."""
    action = callback.data
    if action == "give_sub_start":
        await state.set_state(AdminStates.GIVE_SUB_USERNAME)
        prompt_text = "Введите Telegram username, кому выдать подписку:"
    else: # revoke_sub_start
        await state.set_state(AdminStates.REVOKE_SUB_USERNAME)
        prompt_text = "Введите Telegram username, у кого отозвать подписку:"
    
    await callback.message.edit_text(
        prompt_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
    )
    await callback.answer()

@dp.message(StateFilter(AdminStates.GIVE_SUB_USERNAME, AdminStates.REVOKE_SUB_USERNAME))
async def process_username_for_sub(message: types.Message, state: FSMContext):
    """Обрабатывает введенный username и выдает/отзывает подписку."""
    current_state = await state.get_state()
    username = message.text.lstrip('@')
    
    user_obj = await get_user_by_username(username)
    if not user_obj:
        response_text = f"❌ Не найден @{username}."
    else:
        if current_state == AdminStates.GIVE_SUB_USERNAME:
            await give_subscription_to_user(user_obj.id)
            response_text = f"✅ Подписка выдана @{username}."
        else:  # REVOKE_SUB_USERNAME
            success = await revoke_subscription(user_obj.id)
            response_text = f"🗑 Подписка @{username} отозвана." if success else f"❌ Не найден @{username}."

    await state.clear()
    await message.answer(response_text)
    await message.answer("👑 <b>Админ-панель</b> 👑", reply_markup=get_admin_panel_keyboard())

# --- Логика рассылки ---
@dp.callback_query(F.data == "broadcast_start")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    """Запускает сценарий рассылки."""
    await state.set_state(AdminStates.BROADCAST_MESSAGE)
    await callback.message.edit_text(
        "Введите сообщение для рассылки. Оно будет отправлено всем пользователям бота.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
    )
    await callback.answer()

@dp.message(AdminStates.BROADCAST_MESSAGE)
async def process_broadcast_message(message: types.Message, state: FSMContext, bot: Bot):
    """Обрабатывает сообщение для рассылки и отправляет его."""
    broadcast_text = message.text
    await state.clear()

    users = await get_all_users()
    sent_count = 0
    failed_count = 0

    await message.answer(f"Начинаю рассылку... Всего пользователей: {len(users)}")

    for user in users:
        try:
            await bot.send_message(user.id, broadcast_text)
            sent_count += 1
            await asyncio.sleep(0.05)  # Небольшая задержка, чтобы не спамить API
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user.id}: {e}")
            failed_count += 1

    await message.answer(f"✅ Рассылка завершена!\n\nОтправлено: {sent_count}\nНе удалось отправить: {failed_count}")
    await message.answer("👑 <b>Админ-панель</b> 👑", reply_markup=get_admin_panel_keyboard())

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
    logger.info("Остановка бота и удаление вебхука...")
    await bot.delete_webhook()

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

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main_webhook())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
