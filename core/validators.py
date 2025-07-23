import os
import logging
import httpx
from typing import Tuple, Optional
from aiogram.types import Message
from aiogram import Bot
import aiohttp

# --- Конфигурация Face++ ---
FACEPP_API_KEY = os.getenv("FACEPP_API_KEY")
FACEPP_API_SECRET = os.getenv("FACEPP_API_SECRET")
FACEPP_DETECT_URL = "https://api-us.faceplusplus.com/facepp/v3/detect"

logger = logging.getLogger(__name__)

async def detect_face(photo_bytes: bytes) -> dict:
    """Sends photo to Face++ detect API and returns the result."""
    params = {
        'api_key': FACEPP_API_KEY,
        'api_secret': FACEPP_API_SECRET,
        'return_landmark': 2, # 1 for 83 points, 2 for 106 points
        'return_attributes': 'gender,age,headpose,beauty,skinstatus'
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(FACEPP_DETECT_URL, data={'image_file': photo_bytes}, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Face++ API error: {response.status}, {error_text}")
                    return {"error_message": f"API request failed with status {response.status}"}
        except aiohttp.ClientError as e:
            logger.error(f"Aiohttp client error: {e}")
            return {"error_message": "Failed to connect to face analysis service."}

async def validate_and_analyze_photo(message: Message, bot: Bot, is_front: bool) -> Tuple[bool, dict or str]:
    """Validates photo for correct head pose and runs Face++ analysis."""
    file_id = message.photo[-1].file_id
    file_info = await bot.get_file(file_id)
    file_path = file_info.file_path
    photo_bytes = await bot.download_file(file_path)

    pose_type = 'front' if is_front else 'profile'
    
    try:
        # 1. Анализ для определения позы
        detect_result = await detect_face(photo_bytes.read())
        if 'error_message' in detect_result:
            logger.error(f"Ошибка Face++ API при валидации: {detect_result['error_message']}")
            return False, "Не удалось обработать фото. Попробуйте другое."
        
        if not detect_result.get('faces'):
            return False, "Лицо на фото не найдено. Пожалуйста, загрузите более четкое изображение."

        attributes = detect_result['faces'][0].get('attributes', {})
        headpose = attributes.get('headpose', {})
        yaw_angle = headpose.get('yaw_angle', 0)

        # 2. Валидация позы
        is_valid_pose, error_msg = check_head_pose(yaw_angle, is_front)
        if not is_valid_pose:
            logger.warning(f"Неверная поза для {pose_type}. Угол: {yaw_angle:.2f}. Сообщение: {error_msg}")
            return False, error_msg

        logger.info(f"Фото для позы '{pose_type}' успешно прошло валидацию. Угол: {yaw_angle}")

        # 3. Возвращаем полный результат анализа
        return True, detect_result

    except Exception as e:
        logger.error(f"Критическая ошибка в validate_and_analyze_photo для {pose_type}: {e}", exc_info=True)
        return False, "Произошла внутренняя ошибка сервера. Попробуйте позже."


def check_head_pose(yaw_angle: float, is_front: bool) -> (bool, str):
    """Checks if the head pose is suitable for the required photo type (front or profile)."""
    if is_front:
        if abs(yaw_angle) > 15:
            return False, f"❌ **Неверный ракурс.**\n\nВаше лицо повернуто на {abs(yaw_angle):.1f}°. Для фото анфас допустимо отклонение до 15°.\n\n*Пожалуйста, смотрите прямо в камеру.*"
    else: # is_profile
        if abs(yaw_angle) < 60 or abs(yaw_angle) > 100:
            return False, f"❌ **Неверный ракурс.**\n\nВаше лицо повернуто на {abs(yaw_angle):.1f}°. Для фото в профиль нужен поворот около 90° (от 60° до 100°).\n\n*Пожалуйста, поверните голову ровно вбок.*"
    return True, None

async def validate_photo(photo_bytes: bytes, required_pose: str) -> Tuple[bool, str, Optional[dict]]:
    """
    Валидирует фото через Face++.
    Проверяет наличие ровно одного лица и соответствие позы (анфас/профиль).

    :param photo_bytes: Фото в виде байтов.
    :param required_pose: Ожидаемая поза ('front' или 'profile').
    :return: (is_valid, error_message, face_data)
    """
    if not FACEPP_API_KEY or not FACEPP_API_SECRET:
        logging.error("Ключи Face++ не настроены. Валидация фото невозможна.")
        return False, "Ошибка конфигурации сервера.", None

    files = {'image_file': photo_bytes}
    data = {
        'api_key': FACEPP_API_KEY,
        'api_secret': FACEPP_API_SECRET,
        'return_landmark': '2',  # Запрашиваем 106 точек
        'return_attributes': 'headpose,facequality,beauty'  # landmark убран отсюда
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(FACEPP_DETECT_URL, data=data, files=files, timeout=20.0)
            response.raise_for_status()
            result = response.json()
    except httpx.RequestError as e:
        logging.error(f"Ошибка запроса к Face++: {e}")
        return False, "Не удалось связаться с сервисом анализа. Попробуйте позже.", None
    except Exception as e:
        logging.error(f"Непредвиденная ошибка при валидации фото: {e}")
        return False, "Произошла внутренняя ошибка. Попробуйте позже.", None

    if "error_message" in result:
        logging.warning(f"Face++ вернул ошибку: {result['error_message']}")
        return False, f"Сервис анализа вернул ошибку: {result['error_message']}", None

    faces = result.get("faces", [])

    if not faces:
        return False, "На фото не найдено ни одного лица. Пожалуйста, попробуйте другое фото.", None

    if len(faces) > 1:
        return False, f"На фото найдено несколько лиц ({len(faces)}). Пожалуйста, выберите фото с одним лицом.", None

    face = faces[0]
    headpose = face.get("attributes", {}).get("headpose", {})
    yaw = abs(headpose.get("yaw_angle", 100))

    if required_pose == 'front' and yaw > 20:
        return False, f"Это фото больше похоже на профиль (угол поворота {int(yaw)}°). Пожалуйста, загрузите фото анфас.", None
    
    if required_pose == 'profile' and yaw < 30:
        return False, f"Это фото больше похоже на анфас (угол поворота {int(yaw)}°). Пожалуйста, загрузите фото в профиль.", None

    logging.info(f"Фото для позы '{required_pose}' успешно прошло валидацию. Угол: {yaw}")
    return True, "Фото принято!", face
