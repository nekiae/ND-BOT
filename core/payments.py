import os
from uuid import uuid4
from yookassa import Configuration, Payment

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
    payment = Payment.create({
        "amount": {
            "value": amount,
            "currency": currency
        },
        "confirmation": {
            "type": "redirect",
            # URL, куда вернется пользователь после оплаты. Можно указать URL бота.
            "return_url": f"https://t.me/{os.getenv('BOT_USERNAME', '')}"
        },
        "capture": True,
        "description": f"Подписка HD | Lookism для пользователя {user_id}",
        "metadata": {
            "user_id": str(user_id)
        }
    }, idempotence_key)

    return payment
