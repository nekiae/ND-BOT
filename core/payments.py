import os
import logging
import json
from uuid import uuid4
from yookassa import Configuration, Payment
from requests.exceptions import HTTPError

# --- Загрузка конфигурации ЮKassa ---
shop_id = os.getenv("YOOKASSA_SHOP_ID")
secret_key = os.getenv("YOOKASSA_SECRET_KEY")

if shop_id and secret_key:
    Configuration.account_id = shop_id
    Configuration.secret_key = secret_key
else:
    print("⚠️ YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY не найдены. Функционал оплаты будет недоступен.")

def create_yookassa_payment(user_id: int, amount: str, bot_username: str, currency: str = "RUB") -> Payment | None:
    """
    Создает платеж в ЮKassa и возвращает объект платежа.
    В metadata сохраняем user_id для идентификации при обработке вебхука.
    """
    if not shop_id or not secret_key:
        return None

    idempotence_key = str(uuid4())
    try:
        payment = Payment.create({
            "amount": {
                "value": amount,
                "currency": currency
            },
            'confirmation': {
                'type': 'redirect',
                'return_url': f"https://t.me/{bot_username}"
            },
            "capture": True,
            "description": f"Подписка на ND | Lookism (1 месяц) для user_id:{user_id}",
            "metadata": {
                "user_id": str(user_id)
            },
            "receipt": {
                "customer": {
                    # ВАЖНО: Для реальных платежей здесь должен быть email или телефон пользователя
                    "email": f"user_{user_id}@example.com",
                },
                "items": [
                    {
                        "description": "Подписка на ND | Lookism (1 месяц)",
                        "quantity": "1.00",
                        "amount": {
                            "value": amount,
                            "currency": currency
                        },
                        "vat_code": "1" 
                    }
                ]
            }
        }, idempotence_key)
        return payment
    except HTTPError as e:
        logging.error("❌ Ошибка создания платежа YooKassa!")
        logging.error(f"Статус-код: {e.response.status_code}")
        try:
            error_details = e.response.json()
            logging.error(f"Тело ответа: {json.dumps(error_details, indent=2, ensure_ascii=False)}")
        except Exception:
            logging.error(f"Тело ответа (не JSON): {e.response.text}")
        return None
