import os
import logging
from openai import AsyncOpenAI

# --- Инициализация логгера ---
logger = logging.getLogger(__name__)

# --- Клиент DeepSeek ---
# Мы используем клиент OpenAI, так как API DeepSeek совместим с ним.
# Это стандартный и надежный способ.
client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1"
)

async def get_ai_answer(system_prompt: str, user_prompt: str) -> str:
    """
    Асинхронно получает ответ от модели DeepSeek.

    Args:
        system_prompt: Системный промпт для модели.
        user_prompt: Пользовательский промпт.

    Returns:
        Строка с ответом от AI или сообщение об ошибке.
    """
    logger.info(f"Запрос к DeepSeek API. System prompt: {system_prompt[:100]}... User prompt: {user_prompt[:100]}...")
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=4096,
            temperature=0.7,
        )
        ai_response = response.choices[0].message.content
        logger.info(f"Получен ответ от DeepSeek API: {ai_response[:100]}...")
        return ai_response
    except Exception as e:
        logger.error(f"Ошибка при обращении к DeepSeek API: {e}", exc_info=True)
        return "К сожалению, произошла ошибка при обращении к AI. Попробуйте позже."
        raise
