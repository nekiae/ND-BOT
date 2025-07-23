from aiohttp import web
from aiogram import Bot
import logging

from core.database import grant_subscription

async def yookassa_webhook_handler(request: web.Request):
    """Обрабатывает входящие вебхуки от YooKassa."""
    try:
        data = await request.json()
        logging.info(f"🔔 Получен вебхук от YooKassa: {data}")

        # Проверяем, что это событие успешной оплаты
        if data.get('event') == 'payment.succeeded':
            payment_object = data.get('object', {})
            metadata = payment_object.get('metadata', {})
            user_id = metadata.get('user_id')

            if not user_id:
                logging.error("❌ Ошибка в вебхуке: отсутствует user_id в metadata.")
                return web.Response(status=400) # Bad Request

            try:
                user_id = int(user_id)
                # Выдаем подписку
                grant_subscription(user_id)

                # Получаем объект бота из контекста приложения
                bot: Bot = request.app['bot']
                
                # Отправляем пользователю уведомление об успехе
                await bot.send_message(
                    user_id,
                    "🎉 **Оплата прошла успешно!**\n\n"
                    "Ваша подписка активна. Теперь вам доступны все эксклюзивные возможности!"
                )

            except (ValueError, TypeError) as e:
                logging.error(f"❌ Некорректный user_id в вебхуке: {user_id}. Ошибка: {e}")
                return web.Response(status=400) # Bad Request
            except Exception as e:
                logging.error(f"❌ Ошибка при обработке вебхука для user_id {user_id}: {e}")
                return web.Response(status=500) # Internal Server Error

        # Если это не 'payment.succeeded', просто подтверждаем получение
        return web.Response(status=200)

    except Exception as e:
        logging.error(f"❌ Критическая ошибка в обработчике вебхуков: {e}")
        return web.Response(status=500)
