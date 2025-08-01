import asyncio
import logging

from aiogram import Bot, F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, Message
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.states import AdminAmbassador, AdminStates, IsAdminFilter
from database import (
    confirm_referral_payouts, get_all_ambassadors,
    get_all_users, get_bot_statistics,
    get_pending_payouts_count, get_referral_stats,
    get_subscription_stats, get_user_by_username,
    get_user_detailed_stats, give_subscription_to_user,
    revoke_subscription, set_ambassador_status,
    get_subscribed_users, get_unsubscribed_users # For targeted broadcast
)

logger = logging.getLogger(__name__)
admin_router = Router()
# Применяем фильтр ко всем хендлерам в этом роутере для безопасности
admin_router.message.filter(IsAdminFilter())
admin_router.callback_query.filter(IsAdminFilter())


def get_admin_panel_keyboard():
    """Возвращает клавиатуру для главной панели администратора."""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats"))
    keyboard.row(InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="broadcast_start"))
    keyboard.row(InlineKeyboardButton(text="➕ Выдать подписку", callback_data="give_sub_start"))
    keyboard.row(InlineKeyboardButton(text="➖ Отозвать подписку", callback_data="revoke_sub_start"))
    keyboard.row(InlineKeyboardButton(text="👑 Амбассадоры", callback_data="manage_ambassadors"))
    keyboard.row(InlineKeyboardButton(text="🔍 Статистика пользователя", callback_data="user_stats_start"))
    return keyboard.as_markup()


@admin_router.callback_query(F.data == "user_stats_start")
async def user_stats_start(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает username для показа его статистики."""
    await state.set_state(AdminStates.USER_STATS_USERNAME)
    await callback.message.edit_text("Введите username пользователя (можно без @):")
    await callback.answer()


@admin_router.message(StateFilter(AdminStates.USER_STATS_USERNAME), F.text)
async def process_user_stats(message: types.Message, state: FSMContext):
    username = message.text.strip().lstrip('@')
    user_obj = await get_user_by_username(username)
    if not user_obj:
        await message.answer(f"❌ Пользователь @{username} не найден.")
    else:
        stats = await get_user_detailed_stats(user_obj.id)
        sub_line = (
            f"Активна до: {stats['active_until'].strftime('%d.%m.%Y')}" if stats['subscription_active'] else "Нет активной подписки"
        )
        text = (
            f"👤 <b>Пользователь @{username}</b> (ID {user_obj.id})\n\n"
            f"📅 Подписка: {sub_line}\n"
            f"📊 Анализов осталось: {stats['analyses_left']} | Сообщений: {stats['messages_left']}\n"
        )
        if stats['is_ambassador']:
            text += (
                "\n👑 <b>Амбассадор</b>\n"
                f"Всего оплативших: {stats['total_paid_referrals']}\n"
                f"Ожидают выплаты: {stats['pending_payouts']}"
            )
        await message.answer(text, disable_web_page_preview=True)
    await state.clear()


@admin_router.callback_query(F.data == "admin_panel")
async def handle_admin_panel(callback: types.CallbackQuery, state: FSMContext):
    """Показывает главное меню админ-панели и сбрасывает состояние."""
    await state.clear()
    await callback.message.edit_text(
        "👑 <b>Админ-панель</b> 👑",
        reply_markup=get_admin_panel_keyboard()
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin_stats")
async def handle_admin_stats(callback: types.CallbackQuery):
    """Показывает расширенную статистику бота."""
    try:
        bot_stats = await get_bot_statistics()
        sub_stats = await get_subscription_stats()
        pending_payouts = await get_pending_payouts_count()

        # Формируем детальную строку по подпискам
        other_subs_line = f"\n   - Другие (старые/неопределенные): <b>{sub_stats['total_other']}</b>" if sub_stats['total_other'] > 0 else ""
        
        stats_text = (
            f"<b>📊 Статистика Бота</b>\n\n"
            f"<b>Общее:</b>\n"
            f"- Всего пользователей: <b>{bot_stats['total_users']}</b>\n"
            f"- Амбассадоры (ожидают выплаты): <b>{pending_payouts}</b>\n\n"
            f"<b>Подписки:</b>\n"
            f"- Всего активных: <b>{sub_stats['total_active']}</b>\n"
            f"   - Купленные: <b>{sub_stats['total_purchased']}</b>\n"
            f"   - Выданные админом: <b>{sub_stats['total_granted']}</b>{other_subs_line}\n\n"
            f"<b>Динамика (новые активные подписки):</b>\n"
            f"- За 24 часа: <b>{sub_stats['new_24h']}</b>\n"
            f"- За 48 часов: <b>{sub_stats['new_48h']}</b>\n"
            f"- За 7 дней: <b>{sub_stats['new_7d']}</b>\n"
        )

        await callback.message.edit_text(
            stats_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
            ])
        )
    except Exception as e:
        logging.error(f"Error in handle_admin_stats: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка при загрузке статистики.")
    finally:
        await callback.answer()


# --- Управление Амбассадорами ---
@admin_router.callback_query(F.data.startswith("confirm_payouts_"))
async def confirm_payouts(callback: types.CallbackQuery):
    """Confirms referral payouts for a specific ambassador."""
    try:
        ambassador_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка: неверный ID амбассадора.", show_alert=True)
        return

    cleared_count = await confirm_referral_payouts(ambassador_id)

    if cleared_count > 0:
        await callback.answer(f"✅ Сброшено {cleared_count} ожидающих выплат.", show_alert=True)
    else:
        await callback.answer("Нет выплат для сброса.", show_alert=True)

    # Refresh the list
    await list_ambassadors(callback, should_answer=False)


@admin_router.callback_query(F.data == "list_ambassadors")
async def list_ambassadors(callback: types.CallbackQuery, should_answer: bool = True):
    """Displays a list of all ambassadors with their stats."""
    ambassadors = await get_all_ambassadors()
    if not ambassadors:
        await callback.answer("Список амбассадоров пуст.", show_alert=True)
        return

    response_text = "<b>👑 Список Амбассадоров:</b>\n\n"
    keyboard = InlineKeyboardBuilder()

    for amb in ambassadors:
        stats = await get_referral_stats(amb.id)
        username = f"@{amb.username}" if amb.username else f"ID: {amb.id}"
        response_text += (
            f"<b>{username}</b>\n"
            f"  - Ожидают выплаты: <code>{stats['pending_payouts']}</code>\n"
            f"  - Всего оплативших: <code>{stats['total_paid_referrals']}</code>\n"
        )
        # Add a button to reset pending payouts if there are any
        if stats['pending_payouts'] > 0:
            response_text += f"  - <code><a href='tg://user?id={amb.id}'>Сбросить выплаты</a></code>\n\n"
            keyboard.add(InlineKeyboardButton(
                text=f"Сбросить {stats['pending_payouts']} для {username}",
                callback_data=f"confirm_payouts_{amb.id}"
            ))
        else:
            response_text += "\n"

    keyboard.adjust(1)  # Make buttons full width
    keyboard.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_ambassadors"))

    await callback.message.edit_text(response_text, reply_markup=keyboard.as_markup())
    if should_answer:
        await callback.answer()


@admin_router.callback_query(F.data == "manage_ambassadors")
async def manage_ambassadors_start(callback: types.CallbackQuery):
    """Shows the ambassador management panel."""
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📋 Список", callback_data="list_ambassadors"))
    keyboard.add(InlineKeyboardButton(text="➕ Назначить", callback_data="set_ambassador_start"))
    keyboard.add(InlineKeyboardButton(text="➖ Снять статус", callback_data="revoke_ambassador_start"))
    keyboard.row(InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data="admin_panel"))

    await callback.message.edit_text("👑 Управление Амбассадорами", reply_markup=keyboard.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data.in_(["set_ambassador_start", "revoke_ambassador_start"]))
async def handle_ambassador_management_start(callback: types.CallbackQuery, state: FSMContext):
    """Prompts for a username to manage ambassador status."""
    action = callback.data
    if action == "set_ambassador_start":
        await state.set_state(AdminAmbassador.waiting_for_username_to_set)
        prompt_text = "Введите username, чтобы сделать его амбассадором (можно без @):"
    else:  # revoke_ambassador_start
        await state.set_state(AdminAmbassador.waiting_for_username_to_revoke)
        prompt_text = "Введите username, чтобы отозвать статус амбассадора (можно без @):"

    await callback.message.edit_text(prompt_text)
    await callback.answer()


@admin_router.message(StateFilter(AdminAmbassador.waiting_for_username_to_set, AdminAmbassador.waiting_for_username_to_revoke), F.text)
async def process_username_for_ambassador(message: types.Message, state: FSMContext):
    """Processes the username and sets or revokes ambassador status."""
    current_state = await state.get_state()
    username = message.text.strip()
    user = await get_user_by_username(username)

    if not user:
        await message.answer(f"❌ Пользователь с username @{username} не найден.")
        await state.clear()
        return

    if current_state == AdminAmbassador.waiting_for_username_to_set:
        success = await set_ambassador_status(user.id, True)
        response_text = f"✅ @{username} теперь является амбассадором." if success else f"❌ Не удалось назначить @{username} амбассадором."
    else:  # waiting_for_username_to_revoke
        success = await set_ambassador_status(user.id, False)
        response_text = f"🗑 Статус амбассадора для @{username} снят." if success else f"❌ Не удалось снять статус с @{username}."

    await message.answer(response_text)
    await state.clear()


# --- Управление подписками --- #
@admin_router.callback_query(F.data.in_(["give_sub_start", "revoke_sub_start"]))
async def handle_sub_management_start(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает username для управления подпиской."""
    action = callback.data
    if action == "give_sub_start":
        await state.set_state(AdminStates.GIVE_SUB_USERNAME)
        prompt_text = "Введите Telegram username, кому выдать подписку (можно без @):"
    else:  # revoke_sub_start
        await state.set_state(AdminStates.REVOKE_SUB_USERNAME)
        prompt_text = "Введите Telegram username, у кого отозвать подписку (можно без @):"

    await callback.message.edit_text(
        prompt_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
    )
    await callback.answer()


@admin_router.message(StateFilter(AdminStates.GIVE_SUB_USERNAME, AdminStates.REVOKE_SUB_USERNAME), F.text)
async def process_username_for_sub(message: types.Message, state: FSMContext):
    """Обрабатывает введенный username и выдает/отзывает подписку."""
    current_state = await state.get_state()
    username = message.text.lstrip('@')

    user_obj = await get_user_by_username(username)
    if not user_obj:
        response_text = f"❌ Не найден @{username}."
    else:
        if current_state == AdminStates.GIVE_SUB_USERNAME:
            await give_subscription_to_user(user_obj.id)
            response_text = f"✅ Подписка выдана @{username}."
        else:  # REVOKE_SUB_USERNAME
            success = await revoke_subscription(user_obj.id)
            response_text = f"🗑 Подписка @{username} отозвана." if success else f"❌ Не найден @{username}."

    await state.clear()
    await message.answer(response_text)
    await message.answer("👑 <b>Админ-панель</b> 👑", reply_markup=get_admin_panel_keyboard())


# --- Логика рассылки ---
@admin_router.callback_query(F.data == "broadcast_start")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    """Запускает сценарий рассылки, запрашивая аудиторию."""
    await state.set_state(AdminStates.BROADCAST_AUDIENCE)
    
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="Всем пользователям", callback_data="brd_all"))
    keyboard.row(InlineKeyboardButton(text="✅ Только с подпиской", callback_data="brd_subscribed"))
    keyboard.row(InlineKeyboardButton(text="❌ Только без подписки", callback_data="brd_unsubscribed"))
    keyboard.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel"))

    await callback.message.edit_text(
        "Выберите аудиторию для рассылки:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(StateFilter(AdminStates.BROADCAST_AUDIENCE), F.data.startswith("brd_"))
async def process_broadcast_audience(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает выбор аудитории и запрашивает сообщение."""
    audience = callback.data.split('_')[1]
    await state.update_data(audience=audience)
    await state.set_state(AdminStates.BROADCAST_MESSAGE)

    await callback.message.edit_text(
        "Теперь введите сообщение для рассылки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
    )
    await callback.answer()


@admin_router.message(StateFilter(AdminStates.BROADCAST_MESSAGE), F.text)
async def process_broadcast_message(message: types.Message, state: FSMContext, bot: Bot):
    """Обрабатывает сообщение для рассылки и отправляет его выбранной аудитории."""
    broadcast_text = message.text
    user_data = await state.get_data()
    audience = user_data.get('audience')
    await state.clear()

    users = []
    audience_text = ""
    if audience == 'all':
        users = await get_all_users()
        audience_text = "всем пользователям"
    elif audience == 'subscribed':
        users = await get_subscribed_users()
        audience_text = "пользователям с подпиской"
    elif audience == 'unsubscribed':
        users = await get_unsubscribed_users()
        audience_text = "пользователям без подписки"

    if not users:
        await message.answer("Не найдено пользователей для данной аудитории.")
        await message.answer("👑 <b>Админ-панель</b> 👑", reply_markup=get_admin_panel_keyboard())
        return

    sent_count = 0
    failed_count = 0

    await message.answer(f"Начинаю рассылку {audience_text}... Всего получателей: {len(users)}")

    for user in users:
        try:
            await bot.send_message(user.id, broadcast_text)
            sent_count += 1
            await asyncio.sleep(0.05)  # Небольшая задержка, чтобы не спамить API
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user.id}: {e}")
            failed_count += 1

    await message.answer(f"✅ Рассылка завершена!\n\nОтправлено: {sent_count}\nНе удалось отправить: {failed_count}")
    await message.answer("👑 <b>Админ-панель</b> 👑", reply_markup=get_admin_panel_keyboard())
