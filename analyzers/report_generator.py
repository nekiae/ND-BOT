import json
from typing import Dict, Any

from core.integrations.deepseek import get_ai_answer

def get_system_prompt_from_context(file_path: str = 'context.md') -> str:
    """
    Reads the system prompt from the context.md file.

    Args:
        file_path: The path to the context file.

    Returns:
        The extracted system prompt as a string.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract the prompt section
        prompt_start = content.find('# === SYSTEM PROMPT FOR DeepSeek ===')
        if prompt_start == -1:
            return ""  # Or raise an error
        
        prompt_text = content[prompt_start:]
        # Clean up the header
        prompt_text = prompt_text.split('\n', 1)[1].strip()
        return prompt_text
    except FileNotFoundError:
        # Fallback or error handling
        return "" 

async def create_report_for_user(metrics: Dict[str, Any]) -> str:
    """
    Generates a looksmax report based on facial metrics using an AI model.

    Args:
        metrics: A dictionary containing the facial metrics data.

    Returns:
        A string containing the formatted AI-generated report.
    """
    # Конвертируем словарь с метриками в JSON-строку для передачи в AI
    user_metrics_json = json.dumps(metrics, indent=2, ensure_ascii=False)

    # Формируем финальный промпт для пользователя, который будет передан AI
    user_prompt = f"Проанализируй эти метрики и составь отчет, следуя всем инструкциям из системного промпта:\n{user_metrics_json}"

    # Получаем ответ от AI
    system_prompt = get_system_prompt_from_context()
    if not system_prompt:
        # Handle case where prompt could not be loaded
        return "Ошибка: не удалось загрузить системный промпт для анализа."

    ai_response = await get_ai_answer(system_prompt, user_prompt)

    return ai_response
