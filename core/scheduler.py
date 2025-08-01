from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import get_users_with_expiring_subscription


async def check_expiring_subscriptions(bot: Bot):
    """Проверяет подписки и отправляет уведомления пользователям."""
    try:
        # Пользователи, у которых осталось 3 дня
        users_3_days = await get_users_with_expiring_subscription(days_left=3)
        for user in users_3_days:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📈 Получить отчёт по прогрессу", callback_data="start_analysis")]
            ])
            await bot.send_message(
                user.id,
                "У тебя заканчивается подписка. Хочешь получить отчёт по прогрессу за месяц?",
                reply_markup=keyboard
            )

        # Пользователи, у которых остался 1 день
        users_1_day = await get_users_with_expiring_subscription(days_left=1)
        for user in users_1_day:
            await bot.send_message(
                user.id,
                "Ты близок к следующему рэйту. Это не конец для тебя."
            )
    except Exception as e:
        print(f"Ошибка при проверке подписок: {e}") # Логирование ошибки


def setup_scheduler(bot: Bot):
    """Настраивает и возвращает планировщик задач."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow") # Устанавливаем часовой пояс
    # Запускать проверку каждый день в 12:00 по Москве
    scheduler.add_job(check_expiring_subscriptions, 'cron', hour=12, minute=0, args=[bot])
    return scheduler
