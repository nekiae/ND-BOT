from aiohttp import web
from aiogram import Bot
import logging

from database import give_subscription_to_user as grant_subscription

# Предполагаем, что эти значения определены в конфиге
# Если нет, можно задать их здесь как значения по умолчанию
SUBSCRIPTION_ANALYSES = 2
SUBSCRIPTION_MESSAGES = 200

async def yookassa_webhook_handler(request: web.Request):
    """Обрабатывает входящие вебхуки от YooKassa."""
    bot: Bot = request.app['bot']
    data = None
    try:
        data = await request.json()
        logging.info(f"🔔 Получен вебхук от YooKassa: {data}")

        if data.get('event') == 'payment.succeeded':
            payment_info = data.get('object', {})
            user_id = int(payment_info.get('metadata', {}).get('user_id'))

            if user_id:
                await grant_subscription(user_id, analyses=SUBSCRIPTION_ANALYSES, messages=SUBSCRIPTION_MESSAGES, source='purchased')

                new_text = (
                    f"✅ Твоя подписка успешно активирована!\n\n"
                    f"Теперь тебе доступны все функции ND.\n\n"
                    f"Для начала нажми /analyze и я посмотрю на тебя, помогу.\n\n"
                    f"Или напиши мне, и я тебе отвечу, основываясь на терабайтах информации, что в меня загрузили.\n\n"
                    f"Всего у тебя {SUBSCRIPTION_ANALYSES} фото анализа и {SUBSCRIPTION_MESSAGES} сообщений. Действуй."
                )

                await bot.send_message(
                    chat_id=user_id,
                    text=new_text
                )
                logging.info(f"✅ Подписка для user_id {user_id} успешно активирована.")
            else:
                logging.error("Не найден user_id в метаданных платежа.")

        return web.Response(status=200)

    except Exception as e:
        user_id_info = ""
        if data:
            try:
                # Пытаемся безопасно извлечь user_id для лога
                user_id_info = f" для user_id {data['object']['metadata']['user_id']}"
            except (KeyError, TypeError):
                pass # Если не получилось, ничего страшного
        logging.error(f"❌ Ошибка при обработке вебхука{user_id_info}: {e}", exc_info=True)
        return web.Response(status=500, text="Internal Server Error")
