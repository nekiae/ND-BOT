import json
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple

from core.integrations.deepseek import get_deepseek_response
from core.utils import sanitize_html_for_telegram

# --- Math utility functions ---

def get_point(landmarks: Dict[str, Any], point_name: str) -> Tuple[float, float]:
    """Extracts point coordinates by name."""
    point = landmarks.get(point_name, {'x': 0, 'y': 0})
    return point['x'], point['y']

def calculate_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Calculates Euclidean distance between two points."""
    return math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)

def calculate_angle(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Calculates the tilt angle of a line between two points in degrees."""
    return math.degrees(math.atan2(-(p2[1] - p1[1]), p2[0] - p1[0]))

# --- Main metric calculation function ---

def calculate_facial_metrics(front_data: Dict[str, Any], profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculates a comprehensive set of facial metrics from Face++ data."""
    metrics = {}
    front_landmarks = front_data.get('landmark', {})
    front_attributes = front_data.get('attributes', {})
    profile_attributes = profile_data.get('attributes', {})

    if not front_landmarks:
        return {"error": "Front landmark data is missing."}

    # --- Bone Structure ---
    metrics['bizygo'] = calculate_distance(get_point(front_landmarks, 'contour_left_2'), get_point(front_landmarks, 'contour_right_2'))
    metrics['bigonial'] = calculate_distance(get_point(front_landmarks, 'contour_left_6'), get_point(front_landmarks, 'contour_right_6'))
    face_height = calculate_distance(get_point(front_landmarks, 'nose_bridge1'), get_point(front_landmarks, 'contour_chin'))
    if face_height > 0:
        metrics['fwh_ratio'] = metrics['bizygo'] / face_height

    # --- Eyes ---
    metrics['canthal_tilt'] = (calculate_angle(get_point(front_landmarks, 'left_eye_inner_corner'), get_point(front_landmarks, 'left_eye_outer_corner')) + \
                               calculate_angle(get_point(front_landmarks, 'right_eye_inner_corner'), get_point(front_landmarks, 'right_eye_outer_corner'))) / 2
    metrics['interpupil'] = calculate_distance(get_point(front_landmarks, 'left_eye_pupil_center'), get_point(front_landmarks, 'right_eye_pupil_center'))
    eye_height = (calculate_distance(get_point(front_landmarks, 'left_eye_top'), get_point(front_landmarks, 'left_eye_bottom')) + \
                  calculate_distance(get_point(front_landmarks, 'right_eye_top'), get_point(front_landmarks, 'right_eye_bottom'))) / 2
    eye_width = (calculate_distance(get_point(front_landmarks, 'left_eye_inner_corner'), get_point(front_landmarks, 'left_eye_outer_corner')) + \
                 calculate_distance(get_point(front_landmarks, 'right_eye_inner_corner'), get_point(front_landmarks, 'right_eye_outer_corner'))) / 2
    if eye_width > 0:
        metrics['eye_whr'] = eye_width / eye_height

    # --- Mouth / Lips ---
    metrics['mouth_width'] = calculate_distance(get_point(front_landmarks, 'mouth_left_corner'), get_point(front_landmarks, 'mouth_right_corner'))
    metrics['lip_height'] = calculate_distance(get_point(front_landmarks, 'upper_lip_top'), get_point(front_landmarks, 'lower_lip_bottom'))
    metrics['philtrum'] = calculate_distance(get_point(front_landmarks, 'nose_contour_lower_middle'), get_point(front_landmarks, 'upper_lip_top'))

    # --- Profile (from headpose as proxy) ---
    headpose = profile_attributes.get('headpose', front_attributes.get('headpose', {}))
    metrics['gonial_angle'] = 120 - (headpose.get('pitch_angle', 0) * 0.5) # Proxy
    metrics['mand_plane'] = 25 + headpose.get('roll_angle', 0) # Proxy
    metrics['chin_proj'] = 5 + headpose.get('roll_angle', 0) # Proxy
    metrics['nasofrontal'] = 135 + headpose.get('pitch_angle', 0) # Proxy
    metrics['nasolabial'] = 95 + headpose.get('pitch_angle', 0) # Proxy

    # --- Skin ---
    skin_status = front_attributes.get('skinstatus', {})
    metrics['skin_score'] = skin_status.get('health', 0)
    metrics['acne_idx'] = skin_status.get('acne', 0)
    metrics['stain_idx'] = skin_status.get('stain', 0)

    # --- General Score ---
    beauty = front_attributes.get('beauty', {})
    gender = front_attributes.get('gender', {}).get('value', 'Male')
    metrics['beauty_score'] = beauty.get('male_score' if gender == 'Male' else 'female_score', 0)

    # Round all float values for clean output
    for key, value in metrics.items():
        if isinstance(value, float):
            metrics[key] = round(value, 1)

    return metrics

async def generate_report_text(metrics_data: dict) -> str:
    """Generates a full text report based on metrics using AI for analysis."""
    try:
        front_faces = metrics_data.get('front_photo_data', {}).get('faces', [])
        if not front_faces:
            return "Error: Front face analysis data is missing."
        front_data = front_faces[0]

        if 'landmark' not in front_data:
            return "Error: Front landmark data is missing."

        profile_faces = metrics_data.get('profile_photo_data', {}).get('faces', [])
        profile_data = profile_faces[0] if profile_faces else {}

        calculated_metrics = calculate_facial_metrics(front_data, profile_data)
        if "error" in calculated_metrics:
            return f"Error: {calculated_metrics['error']}"
        
        # --- AI Prompting ---
        system_prompt = """
Ты — элитный AI-аналитик 'ND | Lookism'. Твоя задача — создать гипердетализированный, профессиональный и абсолютно честный отчет по анализу внешности. Ты общаешься как эксперт, используя продвинутую lookmaxxing-терминологию.

ВАЖНО:  СОВЕТЫ ДОЛЖНЫ БЫТЬ ПОЛЕЗНЫМИ И ДЕЛЬНЫМИ!

Пиши текста не так просто, слишком дёшево написано напиши как-то с аурой как некий мыслитель реалист чтобы каждое слово имело вес

чуть пафосном, чуть философском как будто говорю с умным другом. добавлять невероятно умные какие-то предложения понял без дешёвых сравнений по типу мы живём как рыбы без воды вот эту хуйню не надо. 

**КЛЮЧЕВЫЕ ПРАВИЛА:**

1.  **ФОРМАТИРОВАНИЕ — ЧИСТЫЙ ТЕКСТ.**
    *   **ЗАПРЕЩЕНО:** Использовать любое Markdown-форматирование (`**`, `*`, `_`, `#`).
    *   **РАЗРЕШЕНО:** Использовать эмодзи для выделения секций (как в шаблоне), дефисы для списков и пустые строки для разделения абзацев.

2.  **LOOKMAXXING-РЕЙТИНГ.**
    *   Обязательно определи и укажи категорию пользователя по шкале lookmaxxing на основе beauty_score:
        *   < 5.0: Sub5 (Требуется значительная работа)
        *   5.0 - 6.5: LTN (Low-Tier Normie)
        *   6.5 - 8.0: MTN (Mid-Tier Normie)
        *   8.0 - 9.0: HTN (High-Tier Normie)
        *   > 9.0: Chadlite/Chad (Элитный уровень)

3.  **МАКСИМАЛЬНАЯ ДЕТАЛИЗАЦИЯ.**
    *   **ЧЕСТНАЯ ОЦЕНКА:** Должна быть развернутым эссе на несколько абзацев. Укажи на 'хало-эффекты' (сильные стороны) и 'фейл-о' (слабые стороны). Сделай глубокий вывод о текущем состоянии и потенциале.
    *   **ПЛАН УЛУЧШЕНИЙ:** Это самая важная часть. План должен быть огромным, подробным и пошаговым. Разбей его на категории (Skincare, Softmaxxing, Hardmaxxing) и временные рамки. Предлагай конкретные методики (mewing, gua sha), типы косметических средств, упражнения и, если применимо, названия процедур (всегда с оговоркой о консультации со специалистом).

4.  **СТИЛЬ И ТЕРМИНОЛОГИЯ.**
    *   Используй профессиональный, почти клинический тон. Активно внедряй термины: проекция, рецессия, максилла, мандибула, кантальный наклон, hunter/prey eyes, FWHR, IPD, гониальный угол, зигоматики, филтрум и т.д. Объясняй их кратко, если это уместно.
"""

        # Фильтруем метрики, чтобы не передавать AI пустые значения
        metrics_string = "\n".join([f"{key}: {value}" for key, value in calculated_metrics.items() if value not in [0.0, 'N/A']])
        next_check_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')

        user_prompt_template = """
**ДАННЫЕ ДЛЯ АНАЛИЗА:**
{metrics_string}

**ЗАДАЧА:**
Заполни ШАБЛОН ОТЧЁТА, используя ДАННЫЕ. Сгенерируй содержимое для `{{tier_label}}`, `{{summary_paragraph}}` и `{{ПЛАН УЛУЧШЕНИЙ}}`, следуя всем правилам из системного промпта.

**ШАБЛОН ОТЧЁТА:**
🏷️ РЕЙТИНГ И КАТЕГОРИЯ
Базовый рейтинг: {beauty_score:.1f}/10
Категория: {{tier_label}}

────────────────────────────────
📊 ДЕТАЛЬНЫЙ АНАЛИЗ МЕТРИК
────────────────────────────────
__METRICS_BLOCK__
────────────────────────────────
💬 ЧЕСТНАЯ ОЦЕНКА
{{summary_paragraph}}
────────────────────────────────

📌 ПЛАН УЛУЧШЕНИЙ
{{ПЛАН УЛУЧШЕНИЙ}}

────────────────────────────────
• Повторный анализ: {next_check_date}
"""

        # --- Динамическое создание блока метрик ---
        metric_lines = {
            'Костная база': [
                ('• Гониальный угол', calculated_metrics.get('gonial_angle'), '°'),
                ('• Bizygomatic / Bigonial', (calculated_metrics.get('bizygo'), calculated_metrics.get('bigonial')), ' мм'),
                ('• FWHR', calculated_metrics.get('fwh_ratio'), '')
            ],
            'Глаза': [
                ('• Кантальный наклон', calculated_metrics.get('canthal_tilt'), '°', True),
                ('• Interpupillary distance', calculated_metrics.get('interpupil'), ' мм'),
                ('• Eye W/H ratio', calculated_metrics.get('eye_whr'), '')
            ],

            'Рот / губы': [
                ('• Ширина рта', calculated_metrics.get('mouth_width'), ' мм'),
                ('• Общая полнота губ', calculated_metrics.get('lip_height'), ' мм'),
                ('• Длина фильтрума', calculated_metrics.get('philtrum'), ' мм')
            ],
            'Профиль': [
                ('• Chin projection', calculated_metrics.get('chin_proj'), ' мм', True),
                ('• Mandibular plane', calculated_metrics.get('mand_plane'), '°')
            ],
            'Кожа': [
                ('• SkinScore', calculated_metrics.get('skin_score'), '/100'),
                ('• Acne index', calculated_metrics.get('acne_idx'), ''),
                ('• Stain index', calculated_metrics.get('stain_idx'), '')
            ]
        }

        metrics_block_parts = []
        for category, items in metric_lines.items():
            category_part = f"🔸 {category}\n"
            item_parts = []
            for item in items:
                label, value, unit = item[0], item[1], item[2]
                is_signed = item[3] if len(item) > 3 else False

                if isinstance(value, tuple):
                    if all(v is not None and v not in [0.0, 'N/A'] for v in value):
                        item_parts.append(f"{label} {value[0]} мм / {value[1]}{unit}")
                elif value is not None and value not in [0.0, 'N/A']:
                    if is_signed:
                        item_parts.append(f"{label} {value:+.1f}{unit}")
                    else:
                        item_parts.append(f"{label} {value}{unit}")
            
            if item_parts:
                metrics_block_parts.append(category_part + "\n".join(item_parts))

        final_metrics_block = "\n\n".join(metrics_block_parts)
        # --- Конец динамического создания блока ---

        user_prompt = user_prompt_template.format(
            metrics_string=metrics_string,
            beauty_score=calculated_metrics.get('beauty_score', 0) / 10.0,
            next_check_date=next_check_date
        ).replace('__METRICS_BLOCK__', final_metrics_block)

        logging.info("Sending request to DeepSeek API with the new professional template...")
                # Вызываем стриминг-функцию и собираем полный ответ
        response_generator = get_deepseek_response(user_prompt=user_prompt, chat_history=[])
        raw_response = "".join([chunk async for chunk in response_generator])
        
        # Очищаем финальный HTML-ответ от Markdown-артефактов перед отправкой
        sanitized_response = sanitize_html_for_telegram(raw_response)
        
        return sanitized_response
    except Exception as e:
        logging.error(f"Критическая ошибка в generate_report_text: {e}", exc_info=True)
        return "Произошла непредвиденная ошибка при создании отчета. Попробуйте, пожалуйста, еще раз позже."
