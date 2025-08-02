import requests
import json
import uuid

# --- НАСТРОЙКИ ---
# ID пользователя, которому будет выдана тестовая подписка
USER_ID_TO_TEST = 5614882710

# URL, на котором работает ваш бот локально
WEBHOOK_URL = "http://127.0.0.1:8080/yookassa/webhook"
# -----------------

def create_test_payment_notification(user_id):
    """Создает фейковое уведомление об успешном платеже от YooKassa."""
    return {
        "type": "notification",
        "event": "payment.succeeded",
        "object": {
            "id": f"test_{uuid.uuid4()}",
            "status": "succeeded",
            "amount": {
                "value": "2000.00",
                "currency": "RUB"
            },
            "description": f"Тестовая подписка для user_id:{user_id}",
            "metadata": {
                "user_id": str(user_id)
            },
            "paid": True,
            "test": True # Важно указать, что это тестовый платеж
        }
    }

def send_test_webhook():
    """Отправляет тестовый вебхук на локальный сервер бота."""
    payload = create_test_payment_notification(USER_ID_TO_TEST)
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    print(f"🚀 Отправка тестового вебхука для User ID: {USER_ID_TO_TEST} на {WEBHOOK_URL}")
    print("---")
    
    try:
        response = requests.post(WEBHOOK_URL, headers=headers, json=payload, timeout=10)
        
        print(f"✅ Ответ от сервера (Статус: {response.status_code}):")
        if response.text:
            print(response.text)
        else:
            print("(пустой ответ)")
            
        if response.status_code == 200:
            print("\n🎉 Успех! Сервер обработал запрос. Проверяйте сообщение от бота в Telegram.")
        else:
            print(f"\n❌ Ошибка! Сервер вернул статус {response.status_code}. Проверьте логи бота.")
            
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Критическая ошибка: Не удалось подключиться к серверу бота по адресу {WEBHOOK_URL}.")
        print("Убедитесь, что ваш бот (main.py) запущен и работает на порту 8080.")
        print(f"Детали ошибки: {e}")

if __name__ == "__main__":
    send_test_webhook()
