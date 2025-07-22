import asyncio
import logging
import os
import json
from typing import Dict, Any

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import httpx

# --- Загрузка конфигурации ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()] if ADMIN_IDS_STR else []
FACEPP_API_KEY = os.getenv("FACEPP_API_KEY")
FACEPP_API_SECRET = os.getenv("FACEPP_API_SECRET")

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Проверка обязательных переменных ---
if not BOT_TOKEN:
    logging.critical("❌ BOT_TOKEN не найден! Завершение работы.")
    exit()
if not ADMIN_IDS:
    logging.warning("⚠️ ADMIN_IDS не указаны. Функции администратора будут недоступны.")

# --- Инициализация бота и диспетчера ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- База данных в памяти (для ДЕМО) ---
users_data = {}

# --- Состояния FSM ---
class AnalysisStates(StatesGroup):
    waiting_front_photo = State()
    waiting_profile_photo = State()
    chat_with_ai = State()

# --- Вспомогательные функции ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_user_data(user_id: int) -> Dict[str, Any]:
    if user_id not in users_data:
        users_data[user_id] = {
            "is_active": False,
            "analyses_left": 0,
            "messages_left": 0,
        }
    return users_data[user_id]

async def send_report_in_chunks(chat_id: int, text: str, chunk_size: int = 4096):
    """Отправляет длинный текст по частям, избегая разрыва строк."""
    if not text:
        return
    for i in range(0, len(text), chunk_size):
        await bot.send_message(chat_id, text[i:i + chunk_size])
        await asyncio.sleep(0.5)

# --- Интеграции API ---
async def process_face(image_bytes: bytes) -> Dict[str, Any]:
    """Анализирует фото через Face++ и возвращает результат или ошибку."""
    if not FACEPP_API_KEY or not FACEPP_API_SECRET:
        logging.warning("⚠️ Ключи Face++ API не настроены.")
        return {"error": "Ключи Face++ API не настроены. Свяжитесь с администратором."}
    
    url = "https://api-us.faceplusplus.com/facepp/v3/detect"
    params = {
        'api_key': FACEPP_API_KEY,
        'api_secret': FACEPP_API_SECRET,
        'return_landmark': '2',
        'return_attributes': 'gender,age,smiling,headpose,facequality,blur,eyestatus,emotion,ethnicity,beauty,mouthstatus,eyegaze,skinstatus'
    }
    files = {'image_file': image_bytes}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=params, files=files, timeout=30.0)
            response.raise_for_status()
            result = response.json()
            if not result.get('faces'):
                logging.warning("❌ Face++: Лицо не найдено.")
                return {"error": "Лицо не найдено на фото. Попробуйте другое изображение."}
            logging.info("✅ Анализ Face++ успешен.")
            return result['faces'][0]
    except httpx.RequestError as e:
        logging.error(f"❌ Ошибка сети при запросе к Face++: {e}")
        return {"error": "Ошибка сети при обращении к Face++. Попробуйте позже."}
    except Exception as e:
        logging.error(f"❌ Неизвестная ошибка Face++ API: {e}")
        return {"error": "Произошла неизвестная ошибка при анализе фото."}

# --- Импорт логики после инициализации ---
from analyzers.lookism_metrics import compute_all
from core.report_logic import create_report_prompt
from core.integrations.deepseek import get_ai_answer

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start."""
    await state.clear()
    user_id = message.from_user.id
    logging.info(f"🚀 Пользователь {user_id} нажал /start")
    user_data = get_user_data(user_id)

    if user_data["is_active"]:
        analyses_left = "Безлимит" if is_admin(user_id) else user_data['analyses_left']
        await message.answer(
            f"🔥 <b>HD | Lookism</b>\n\nТвой ИИ-коуч готов к работе. Осталось анализов: <b>{analyses_left}</b>.\n\nОтправь фото анфас (лицо прямо), чтобы начать.",
        )
        await state.set_state(AnalysisStates.waiting_front_photo)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Активировать ДЕМО (1 анализ)", callback_data="activate_demo")]
        ])
        await message.answer(
            "Добро пожаловать в <b>HD | Lookism</b>!\n\nЭто бот для глубокого анализа внешности и получения персональных рекомендаций.\n\nАктивируйте ДЕМО-доступ, чтобы получить свой первый анализ.",
            reply_markup=keyboard
        )

@dp.callback_query(F.data == "activate_demo")
async def activate_demo(cq: CallbackQuery, state: FSMContext):
    """Активирует ДЕМО-доступ для пользователя."""
    user_id = cq.from_user.id
    user_data = get_user_data(user_id)
    if user_data["is_active"]:
        await cq.answer("У вас уже есть активный доступ.", show_alert=True)
        return

    logging.info(f"🔥 Пользователь {user_id} активировал ДЕМО-доступ.")
    user_data["is_active"] = True
    user_data["analyses_left"] = 1
    user_data["messages_left"] = 20
    await cq.message.edit_text("✅ ДЕМО-доступ активирован! У вас <b>1</b> анализ и <b>20</b> сообщений ИИ-коучу.\n\nТеперь отправьте фото анфас, чтобы начать.")
    await state.set_state(AnalysisStates.waiting_front_photo)
    await cq.answer()

# --- Обработка фото ---
@dp.message(F.photo, StateFilter(AnalysisStates.waiting_front_photo, AnalysisStates.waiting_profile_photo))
async def handle_photos(message: Message, state: FSMContext):
    """Принимает фото анфас и профиль, инициирует анализ."""
    current_state = await state.get_state()
    user_id = message.from_user.id

    if current_state == AnalysisStates.waiting_front_photo:
        logging.info(f"📸 Получено фото анфас от {user_id}")
        await message.answer("✅ Фото анфас принято. Теперь отправь фото в профиль (вид сбоку).")
        file_info = await bot.get_file(message.photo[-1].file_id)
        photo_bytes = await bot.download_file(file_info.file_path)
        await state.update_data(front_photo=photo_bytes.read())
        await state.set_state(AnalysisStates.waiting_profile_photo)

    elif current_state == AnalysisStates.waiting_profile_photo:
        logging.info(f"📸 Получено фото профиля от {user_id}. Запуск анализа.")
        if not is_admin(user_id) and get_user_data(user_id)['analyses_left'] <= 0:
            await message.answer("❌ У вас закончились попытки анализа. Начните заново через /start.")
            await state.clear()
            return

        file_info = await bot.get_file(message.photo[-1].file_id)
        photo_bytes = await bot.download_file(file_info.file_path)
        await state.update_data(profile_photo=photo_bytes.read())
        
        await message.answer("⏳ Оба фото получены. Начинаю глубокий анализ... Это может занять до 2 минут.")
        asyncio.create_task(run_analysis(message, state))

async def run_analysis(message: Message, state: FSMContext):
    """Полный цикл анализа: Face++, расчёт метрик, генерация отчёта DeepSeek."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        user_data = await state.get_data()
        front_photo_bytes = user_data.get('front_photo')
        profile_photo_bytes = user_data.get('profile_photo')

        if not front_photo_bytes or not profile_photo_bytes:
            await bot.send_message(chat_id, "❌ Ошибка: не найдены оба фото. Начните заново с /start.")
            return

        front_analysis = await process_face(front_photo_bytes)
        if 'error' in front_analysis:
            await bot.send_message(chat_id, f"❌ Ошибка фото анфас: {front_analysis['error']}")
            return

        profile_analysis = await process_face(profile_photo_bytes)
        if 'error' in profile_analysis:
            await bot.send_message(chat_id, f"❌ Ошибка фото профиль: {profile_analysis['error']}")
            return

        logging.info("🧠 Расчёт всех луксмакс-метрик...")
        all_metrics = compute_all(front_analysis, profile_analysis)

        logging.info("🤖 Генерация полного отчёта через DeepSeek...")
        system_prompt, user_prompt = create_report_prompt(json.dumps(all_metrics, indent=2, ensure_ascii=False))
        full_report = await get_ai_answer(system_prompt, user_prompt)
        
        if not full_report or "ошибка" in full_report.lower():
            raise Exception(full_report or "Пустой ответ от API")

        # Убираем звездочки для форматирования
        full_report = full_report.replace('**', '').replace('*', '')

        await bot.send_message(chat_id, "✅ Ваш отчёт готов! Сейчас я его пришлю.")
        await send_report_in_chunks(chat_id, full_report)

        if not is_admin(user_id):
            db = get_user_data(user_id)
            db['analyses_left'] -= 1
        
        # Сохраняем отчет в FSM для последующего диалога
        await state.update_data(full_report=full_report)
        await bot.send_message(chat_id, "Вы можете задать мне вопросы по отчёту или начать новый анализ командой /start.")
        await state.set_state(AnalysisStates.chat_with_ai)

    except Exception as e:
        logging.error(f"Критическая ошибка в run_analysis для user {user_id}: {e}", exc_info=True)
        await bot.send_message(chat_id, "❌ Произошла критическая ошибка во время анализа. Пожалуйста, начните заново с /start.")
    except Exception as e:
        logging.error(f"Критическая ошибка в run_analysis для user {user_id}: {e}", exc_info=True)
        await bot.send_message(chat_id, "❌ Произошла критическая ошибка во время анализа. Пожалуйста, начните заново с /start.")
        await state.clear()

# --- Чат с ИИ ---
@dp.message(F.text, StateFilter(AnalysisStates.chat_with_ai))
async def chat_with_ai_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_db = get_user_data(user_id)

    if not is_admin(user_id):
        if user_db['messages_left'] <= 0:
            await message.answer("❌ У вас закончились сообщения для ИИ-коуча. Начните новый анализ через /start, чтобы получить больше.")
            await state.clear()
            return
        user_db['messages_left'] -= 1

    user_data = await state.get_data()
    full_report = user_data.get('full_report', 'Контекст предыдущего анализа утерян.')

    await message.answer("⏳ Думаю над вашим вопросом...")

    system_prompt = (
        f"Ты — HD | Lookism AI, ИИ-коуч. Тебе предоставлен предыдущий анализ внешности пользователя. "
        f"Твоя задача — отвечать на его вопросы, основываясь на данных из этого анализа. "
        f"ВАЖНО: Если пользователь спрашивает, как выполнять какую-либо методику или упражнение (например, 'что такое мьюинг?' или 'как делать упражнения для челюсти?'), "
        f"ты должен дать максимально подробную, пошаговую инструкцию, как настоящий тренер. Объясняй каждый шаг. "
        f"В остальных случаях будь краток и по делу.\n\n"
        f"Вот полный отчет для контекста:\n---НАЧАЛО ОТЧЕТА---\n{full_report}\n---КОНЕЦ ОТЧЕТА---"
    )
    user_prompt = f"Основываясь на отчете, ответь на мой вопрос: {message.text}"

    try:
        ai_response = await get_ai_answer(system_prompt, user_prompt)
        # Убираем звездочки для форматирования
        ai_response = ai_response.replace('**', '').replace('*', '')
        await message.answer(ai_response)
        messages_left_info = f"Осталось сообщений: {user_db['messages_left']}" if not is_admin(user_id) else ""
        await message.answer(f"Что-нибудь еще? {messages_left_info}")
    except Exception as e:
        logging.error(f"Ошибка в чате с ИИ для user {user_id}: {e}")
        await message.answer("❌ Произошла ошибка при обработке вашего вопроса. Попробуйте еще раз.")

# --- Запуск бота ---
async def main():
    """Главная функция для запуска бота."""
    logging.info("🚀 Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("✅ Бот остановлен.")
