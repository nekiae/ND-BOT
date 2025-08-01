import os
import numpy as np
import cv2
import logging
import httpx
from typing import Tuple, Optional
from aiogram.types import Message
from aiogram import Bot
import aiohttp
import json

# --- Конфигурация Face++ ---
FACEPP_API_KEY = os.getenv("FACEPP_API_KEY")
FACEPP_API_SECRET = os.getenv("FACEPP_API_SECRET")
FACEPP_DETECT_URL = "https://api-us.faceplusplus.com/facepp/v3/detect"

logger = logging.getLogger(__name__)

def is_bright_enough(img_bytes: bytes) -> bool:
    """Checks if the image is bright enough for analysis."""
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return False # Не удалось декодировать изображение
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return gray.mean() >= 40


async def detect_face(photo_bytes: bytes) -> dict:
    """Sends photo to Face++ detect API and returns the result."""
    data = aiohttp.FormData()
    data.add_field('api_key', FACEPP_API_KEY)
    data.add_field('api_secret', FACEPP_API_SECRET)
    data.add_field('return_landmark', '2')
    data.add_field('return_attributes', "gender,age,beauty,facequality,eyestatus,emotion,ethnicity,mouthstatus,eyegaze,headpose,skinstatus")
    data.add_field('image_file', photo_bytes, filename='photo.jpg', content_type='image/jpeg')

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(FACEPP_DETECT_URL, data=data) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Face++ API error: {response.status}, Body: {error_text}")
                    try:
                        # Face++ often returns a JSON with an 'error_message' field
                        error_json = json.loads(error_text)
                        return {"error_message": error_json.get("error_message", f"API request failed with status {response.status}")}
                    except json.JSONDecodeError:
                        return {"error_message": f"API request failed with status {response.status}. Could not parse error response."}
        except aiohttp.ClientError as e:
            logger.error(f"Aiohttp client error: {e}")
            return {"error_message": "Failed to connect to face analysis service."}

def check_head_pose(yaw_angle: float, is_front: bool) -> (bool, str):
    """Checks if the head pose is suitable for the required photo type (front or profile)."""
    if is_front:
        if abs(yaw_angle) > 15:
            return False, f"❌ **Неверный ракурс.**\n\nВаше лицо повернуто на {abs(yaw_angle):.1f}°. Для фото анфас допустимо отклонение до 15°.\n\n*Пожалуйста, смотрите прямо в камеру.*"
    else: # is_profile
        if abs(yaw_angle) < 60 or abs(yaw_angle) > 100:
            return False, f"❌ **Неверный ракурс.**\n\nВаше лицо повернуто на {abs(yaw_angle):.1f}°. Для фото в профиль нужен поворот около 90° (от 60° до 100°).\n\n*Пожалуйста, поверните голову ровно вбок.*"
    return True, None

