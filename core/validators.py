import os
import logging
import httpx
from typing import Tuple, Optional

# --- Конфигурация Face++ ---
FACEPP_API_KEY = os.getenv("FACEPP_API_KEY")
FACEPP_API_SECRET = os.getenv("FACEPP_API_SECRET")
FACEPP_DETECT_URL = "https://api-us.faceplusplus.com/facepp/v3/detect"

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
        'return_attributes': 'headpose,facequality'
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
