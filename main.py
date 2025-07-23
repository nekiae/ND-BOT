# --- Загрузка .env должна быть в самом начале ---
import hmac
import hashlib
import json
from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# --- Импорт модулей проекта ---
from core.payments import create_yookassa_payment
from database import create_db_and_tables, add_user, check_subscription, give_subscription_to_user
from core.validators import validate_photo
# Динамические импорты, которые требуют загруженный bot, останутся в функциях

# --- Логирование --- #
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

# --- Конфигурация --- #
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(',') if admin_id]
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")

# Настройки веб-сервера и вебхуков
WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", 8080))
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL") # Например, https://your-app-name.railway.app

# Пути для вебхуков
TELEGRAM_WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}' # Безопасный путь
YOOKASSA_WEBHOOK_PATH = os.getenv("YOOKASSA_WEBHOOK_PATH", "/yookassa/webhook")

# --- Инициализация --- #
if not BOT_TOKEN:
    raise ValueError("Токен бота не найден. Проверьте .env файл.")

dp = Dispatcher()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# --- Состояния FSM --- #
class Form(StatesGroup):
    waiting_for_front_photo = State()
    waiting_for_profile_photo = State()
    chatting_with_ai = State()

# --- Клавиатуры --- #
def get_main_keyboard(is_admin_user: bool):
    buttons = [
        [InlineKeyboardButton(text="📸 Начать анализ", callback_data="start_analysis")],
        [InlineKeyboardButton(text="⭐️ Оформить подписку", callback_data="subscribe")],
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
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start. Разделяет админов и обычных пользователей."""
    await state.clear()
    user_id = message.from_user.id
    logging.info(f"🚀 Пользователь {user_id} нажал /start")
    await add_user(user_id) # Добавляем пользователя в БД, если его там нет

    if is_admin(user_id):
        await message.answer(
            "<b>👑 Добро пожаловать, Администратор!</b>\n\n"
            "У вас полный безлимитный доступ ко всем функциям.\n\n"
            "Чтобы начать новый анализ, нажмите кнопку ниже.",
            reply_markup=get_main_keyboard(True)
        )
    else:
        welcome_text = (
            "<b>Добро пожаловать в HD | Lookism!</b>\n\n"
            "Я — ваш персональный ИИ-ассистент для анализа внешности. "
            "Отправьте мне свои фотографии, и я предоставлю детальный разбор "
            "ваших антропометрических данных и симметрии лица.\n\n"
            "⭐️ <b>Для начала, нажмите на кнопку ниже.</b>"
        )
        await message.answer(welcome_text, reply_markup=get_main_keyboard(False))

@dp.callback_query(F.data == "subscribe")
async def process_payment_start(cq: CallbackQuery):
    """Создает и отправляет пользователю ссылку на оплату."""
    user_id = cq.from_user.id
    logging.info(f"💰 Пользователь {user_id} инициировал оплату.")

    amount = "100.00"
    description = "Подписка на HD | Lookism (1 месяц)"

    payment_url, _ = await create_yookassa_payment(amount, description, {'user_id': user_id})

    if payment_url:
        await cq.message.answer(
            "Для оформления подписки, пожалуйста, перейдите по ссылке ниже.",
            reply_markup=get_payment_keyboard(payment_url)
        )
    else:
        await cq.message.answer("Произошла ошибка при создании платежа. Попробуйте позже.")
    await cq.answer()

@dp.callback_query(F.data == "start_analysis")
async def cmd_analyze(cq: CallbackQuery, state: FSMContext):
    """Запускает новый анализ для пользователя."""
    user_id = cq.from_user.id
    is_user_admin = is_admin(user_id)
    has_sub = await check_subscription(user_id)

    if not is_user_admin and not has_sub:
        await cq.message.answer(
            "У вас нет активной подписки или попыток анализа. Пожалуйста, оформите подписку.",
            reply_markup=get_main_keyboard(False)
        )
        await cq.answer()
        return

    await state.set_state(Form.waiting_for_front_photo)
    await cq.message.answer(
        "<b>Начинаем новый анализ.</b>\n\n"
        "Пожалуйста, отправьте мне ваше фото <b>анфас</b> (лицом к камере)."
    )
    await cq.answer()

# --- Обработка фото ---
@dp.message(Form.waiting_for_front_photo, F.photo)
async def handle_front_photo(message: Message, state: FSMContext):
    """Принимает и ВАЛИДИРУЕТ фото анфас."""
    await message.answer("⏳ Анализирую фото анфас...")
    is_valid, error_message = await validate_photo(message.photo[-1])

    if not is_valid:
        await message.answer(f"❌ Ошибка: {error_message} Пожалуйста, загрузите другое фото.")
        return

    await state.update_data(front_photo_file_id=message.photo[-1].file_id)
    await state.set_state(Form.waiting_for_profile_photo)
    await message.answer(
        "✅ Отлично! Теперь, пожалуйста, отправьте ваше фото в <b>профиль</b> (боком)."
    )

@dp.message(Form.waiting_for_profile_photo, F.photo)
async def handle_profile_photo(message: Message, state: FSMContext):
    """Принимает, ВАЛИДИРУЕТ фото профиля и запускает полный анализ."""
    await message.answer("⏳ Анализирую фото профиля...")
    is_valid, error_message = await validate_photo(message.photo[-1], is_profile=True)

    if not is_valid:
        await message.answer(f"❌ Ошибка: {error_message} Пожалуйста, загрузите другое фото профиля.")
        return

    await state.update_data(profile_photo_file_id=message.photo[-1].file_id)
    await message.answer(
        "✅ Все фотографии приняты! Начинаю глубокий анализ. "
        "Это может занять несколько минут... Я пришлю отчет, как только он будет готов."
    )
    asyncio.create_task(run_analysis(message, state))

async def run_analysis(message: Message, state: FSMContext):
    """Полный цикл анализа: Face++, расчёт метрик, генерация отчёта DeepSeek."""
    from analyzers.lookism_metrics import compute_all
    from core.report_logic import create_report_prompt
    from core.integrations.deepseek import get_ai_answer

    user_id = message.from_user.id
    user_data = await state.get_data()
    front_photo_id = user_data.get('front_photo_file_id')
    profile_photo_id = user_data.get('profile_photo_file_id')

    try:
        metrics = await compute_all(bot, front_photo_id, profile_photo_id)
        report_prompt = create_report_prompt(metrics)
        
        await message.answer("🧠 Отправляю данные нейросети для генерации финального отчета...")
        ai_report = await get_ai_answer(report_prompt)

        await message.answer("<b>🎉 Ваш персональный отчет готов!</b>")
        for i in range(0, len(ai_report), 4096):
            await message.answer(ai_report[i:i + 4096])

        await state.update_data(last_report=ai_report)
        await state.set_state(Form.chatting_with_ai)
        await message.answer("Теперь вы можете задать уточняющие вопросы по отчету.")

        if not is_admin(user_id):
            # TODO: Добавить логику списания попытки из БД
            pass

    except Exception as e:
        logging.error(f"Ошибка в процессе анализа для user {user_id}: {e}", exc_info=True)
        await message.answer(
            "Произошла непредвиденная ошибка во время анализа. "
            "Попробуйте позже или обратитесь в поддержку."
        )
        await state.clear()

# --- Чат с ИИ ---
@dp.message(Form.chatting_with_ai, F.text)
async def chat_with_ai_handler(message: Message, state: FSMContext):
    from core.integrations.deepseek import get_ai_answer
    user_data = await state.get_data()
    report_context = user_data.get('last_report')

    wait_message = await message.answer("💬 Думаю над вашим вопросом...")
    ai_response = await get_ai_answer(message.text, context=report_context)
    await wait_message.edit_text(ai_response)

# --- Вебхуки --- #
async def yookassa_webhook_handler(request: web.Request):
    """Обрабатывает вебхуки от ЮKassa."""
    bot_instance = request.app["bot"]
    try:
        body = await request.read()
        event_json = json.loads(body)
    except json.JSONDecodeError:
        logging.error("Ошибка декодирования JSON от ЮKassa.")
        return web.Response(status=400, text="Invalid JSON")

    if YOOKASSA_SECRET_KEY:
        try:
            signature_header = request.headers.get("Webhook-Signature")
            if not signature_header:
                return web.Response(status=400, text="Missing signature")
            
            parts = signature_header.split('=')
            if len(parts) != 2 or parts[0] != 'v1':
                 return web.Response(status=400, text="Invalid signature format")

            computed_signature = hmac.new(YOOKASSA_SECRET_KEY.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(computed_signature, parts[1]):
                logging.warning("Неверная подпись вебхука ЮKassa.")
                return web.Response(status=400, text="Invalid signature")
        except Exception as e:
            logging.error(f"Ошибка при проверке подписи ЮKassa: {e}")
            return web.Response(status=500)

    logging.info(f"🔔 Получен вебхук от ЮKassa: {event_json.get('event')}")

    if event_json.get("event") == "payment.succeeded":
        payment_object = event_json.get("object", {})
        metadata = payment_object.get("metadata", {})
        user_id = metadata.get("user_id")

        if user_id:
            await give_subscription_to_user(int(user_id))
            await bot_instance.send_message(user_id, "🎉 <b>Поздравляем!</b> Ваша подписка успешно активирована.")
        else:
            logging.warning("В вебхуке ЮKassa не найден user_id.")

    return web.Response(status=200)

async def on_startup(app: web.Application):
    """Действия при запуске приложения."""
    bot_instance = app["bot"]
    webhook_url = f"{BASE_WEBHOOK_URL}{TELEGRAM_WEBHOOK_PATH}"
    await bot_instance.set_webhook(webhook_url, drop_pending_updates=True)
    logging.info(f"Установлен вебхук на: {webhook_url}")

async def on_shutdown(app: web.Application):
    """Действия при остановке приложения."""
    bot_instance = app["bot"]
    await bot_instance.delete_webhook()
    logging.info("Вебхук удален.")

# --- Запуск бота --- #
async def main():
    await create_db_and_tables() # Инициализация БД

    if not BASE_WEBHOOK_URL:
        # Режим опроса для локальной разработки
        logging.info("Запуск в режиме опроса (polling)...")
        await bot.delete_webhook(drop_pending_updates=True) # На случай, если вебхук был установлен ранее
        await dp.start_polling(bot)
    else:
        # Режим вебхука для продакшена
        logging.info("Запуск в режиме вебхука...")
        app = web.Application()
        app["bot"] = bot

        # Регистрируем обработчики вебхуков
        app.router.add_post(YOOKASSA_WEBHOOK_PATH, yookassa_webhook_handler)
        telegram_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        telegram_handler.register(app, path=TELEGRAM_WEBHOOK_PATH)
        
        # Регистрируем функции startup/shutdown
        app.on_startup.append(on_startup)
        app.on_shutdown.append(on_shutdown)

        # Запускаем веб-сервер
        setup_application(app, dp, bot=bot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
        await site.start()
        logging.info(f"Веб-сервер запущен на http://{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        await asyncio.Event().wait() # Бесконечное ожидание

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
