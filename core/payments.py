import os
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

def create_yookassa_payment(user_id: int, amount: str, currency: str = "RUB") -> Payment | None:
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
            "confirmation": {
                "type": "redirect",
                "return_url": f"https://t.me/{os.getenv('BOT_USERNAME', '')}"
            },
            "capture": True,
            "description": f"Подписка HD | Lookism для пользователя {user_id}",
            "metadata": {
                "user_id": str(user_id)
            },
            "receipt": {
                "customer": {
                    "email": f"user_{user_id}@example.com"
                },
                "items": [
                    {
                        "description": "Подписка HD | Lookism",
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
        print("❌ Ошибка создания платежа YooKassa!")
        print(f"Статус-код: {e.response.status_code}")
        try:
            print(f"Тело ответа: {e.response.json()}")
        except Exception:
            print(f"Тело ответа (не JSON): {e.response.text}")
        return None
