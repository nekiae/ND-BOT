import os
import aiohttp

# Получаем ключ API из переменных окружения
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
API_URL = "https://api.deepseek.com/chat/completions"

async def get_ai_answer(system_prompt: str, user_prompt: str) -> str:
    """
    Asynchronously sends a request to the DeepSeek API and returns the AI's response.

    Args:
        system_prompt: The system message to guide the AI.
        user_prompt: The user's message or data to be analyzed.

    Returns:
        The content of the AI's response as a string, or an error message.
    """
    if not DEEPSEEK_API_KEY:
        return "Ошибка: Ключ API для DeepSeek не найден. Проверьте .env файл."

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.4,
        "max_tokens": 4096,  # Увеличим лимит для полных отчетов
        "stream": False
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['choices'][0]['message']['content']
                else:
                    error_text = await response.text()
                    return f"Ошибка API DeepSeek: {response.status} - {error_text}"
    except Exception as e:
        return f"Произошла ошибка при обращении к DeepSeek: {e}"
