"""Database configuration and connection management."""

import os
from typing import AsyncGenerator

from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy import text, TIMESTAMP
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column
from sqlmodel import SQLModel, select, func

from models import User, Session, Task
from sqlalchemy import JSON

import logging
logger = logging.getLogger(__name__)


# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables. Please configure it.")

# Convert postgres:// to postgresql+asyncpg:// if needed
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False)

# Create session factory
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def _ensure_referral_columns(conn):
    # This is a hacky way to add columns to the users table if they don't exist
    # This is needed for backward compatibility with older versions of the database
    columns_to_add = {
        "is_ambassador": "BOOLEAN DEFAULT FALSE",
        "referred_by_id": "BIGINT",
        "referral_payout_pending": "BOOLEAN DEFAULT FALSE"
    }

    dialect_name = conn.dialect.name

    if dialect_name == 'sqlite':
        for column, definition in columns_to_add.items():
            result = await conn.execute(text(f"PRAGMA table_info(users);"))
            existing_columns = [row[1] for row in result.fetchall()]
            if column not in existing_columns:
                stmt = f"ALTER TABLE users ADD COLUMN {column} {definition};"
                await conn.execute(text(stmt))
    else:  # Assuming postgresql
        for column, definition in columns_to_add.items():
            stmt = f"ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS {column} {definition};"
            await conn.execute(text(stmt))


async def _ensure_last_analysis_metrics_column(conn):
    """Ensure the last_analysis_metrics column exists."""
    column_name = "last_analysis_metrics"
    dialect_name = conn.dialect.name

    if dialect_name == 'sqlite':
        result = await conn.execute(text(f"PRAGMA table_info(users);"))
        existing_columns = [row[1] for row in result.fetchall()]
        if column_name not in existing_columns:
            await conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} JSON;'))
            logger.info(f"Added '{column_name}' column to 'users' table for sqlite.")
    else:  # Assuming postgresql
        # For PostgreSQL, JSON type is appropriate
        await conn.execute(text(f'ALTER TABLE users ADD COLUMN IF NOT EXISTS {column_name} JSONB;'))
        logger.info(f"Ensured '{column_name}' column exists in 'users' table for postgresql.")


async def _ensure_subscription_source_column(conn):
    """Ensure the subscription_source column exists."""
    column_name = "subscription_source"
    dialect_name = conn.dialect.name

    if dialect_name == 'sqlite':
        result = await conn.execute(text(f"PRAGMA table_info(users);"))
        existing_columns = [row[1] for row in result.fetchall()]
        if column_name not in existing_columns:
            await conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} TEXT;'))
            logger.info(f"Added '{column_name}' column to 'users' table for sqlite.")
    else:  # Assuming postgresql
        await conn.execute(text(f'ALTER TABLE users ADD COLUMN IF NOT EXISTS {column_name} VARCHAR(255);'))
        logger.info(f"Ensured '{column_name}' column exists in 'users' table for postgresql.")


async def _ensure_bigint_columns(conn):
    """Ensure critical id columns are BIGINT (int8) to allow large Telegram IDs."""
    alter_statements = [
        # Convert child FK columns first to avoid constraint errors
        "ALTER TABLE IF EXISTS sessions ALTER COLUMN user_id TYPE BIGINT USING user_id::BIGINT;",
        "ALTER TABLE IF EXISTS tasks ALTER COLUMN session_id TYPE BIGINT USING session_id::BIGINT;",
        # Then convert parent and other columns
        "ALTER TABLE IF EXISTS users ALTER COLUMN id TYPE BIGINT USING id::BIGINT;",
        "ALTER TABLE IF EXISTS users ALTER COLUMN referred_by_id TYPE BIGINT USING referred_by_id::BIGINT;"
    ]
    for stmt in alter_statements:
        try:
            await conn.execute(text(stmt))
        except Exception as exc:
            # Ignore errors where type is already bigint or column missing.
            logger.debug(f"Skipping alter column statement due to: {exc}")

async def create_db_and_tables() -> None:
    """Create database tables."""
    async with engine.begin() as conn:
        logger.info("Creating database tables if they do not exist…")
        await conn.run_sync(SQLModel.metadata.create_all)
        # Ensure new columns exist for referral system
        await _ensure_referral_columns(conn)
        # Ensure critical ID columns are BIGINT to fit Telegram IDs
        await _ensure_bigint_columns(conn)
        # Ensure the new metrics column exists
        await _ensure_last_analysis_metrics_column(conn)
        await _ensure_subscription_source_column(conn)
        logger.info("Database setup complete")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session() as session:
        yield session


async def close_db() -> None:
    """Close database connection."""
    await engine.dispose()


async def add_user(user_id: int, username: str | None = None, referred_by_id: int | None = None) -> None:
    """Add a new user or update their username, optionally with a referrer."""
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if not user:
                session.add(User(id=user_id, username=username, referred_by_id=referred_by_id))
            elif user.username != username:
                user.username = username
            await session.commit()

async def check_subscription(user_id: int) -> bool:
    """Check if a user has an active subscription."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_active_until:
            return False

        # Сделаем is_active_until таймзон-осведомленным, если он еще не такой
        active_until = user.is_active_until
        if active_until.tzinfo is None:
            active_until = active_until.replace(tzinfo=timezone.utc)

        return active_until > datetime.now(timezone.utc)

async def get_users_with_expiring_subscription(days_left: int) -> list[User]:
    """Находит пользователей, у которых подписка истекает через указанное количество дней."""
    async with async_session() as session:
        # Ищем дату в диапазоне от начала до конца указанного дня
        target_date_start = datetime.now(timezone.utc).date() + timedelta(days=days_left)
        target_date_end = target_date_start + timedelta(days=1)

        result = await session.execute(
            select(User).where(
                User.is_active_until >= target_date_start,
                User.is_active_until < target_date_end,
                User.is_active.is_(True) # Проверяем только активных пользователей
            )
        )
        return list(result.scalars().all())

async def get_user(user_id: int) -> User | None:
    """Получает пользователя по его ID и исправляет часовой пояс на лету."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user and user.is_active_until and user.is_active_until.tzinfo is None:
            user.is_active_until = user.is_active_until.replace(tzinfo=timezone.utc)
        return user


async def decrement_user_messages(user_id: int):
    """Уменьшает количество оставшихся сообщений пользователя на 1."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user and user.messages_left > 0:
            user.messages_left -= 1
            await session.commit()

async def save_user_metrics(user_id: int, metrics: dict) -> None:
    """Saves the latest analysis metrics for a user."""
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if user:
                user.last_analysis_metrics = metrics
                await session.commit()
                logger.info(f"Saved latest analysis metrics for user {user_id}")


async def decrement_user_analyses(user_id: int) -> bool:
    """Уменьшает количество оставшихся анализов пользователя на 1."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user and user.analyses_left > 0:
            user.analyses_left -= 1
            await session.commit()
            return True
        return False


async def give_subscription_to_user(
    user_id: int, 
    days: int = 30, 
    analyses: int = 2, 
    messages: int = 200, 
    source: str = 'granted'  # 'granted' or 'purchased'
) -> None:
    """Grants or extends a subscription and handles referral logic."""
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if not user:
                user = User(id=user_id)
                session.add(user)
            
            if user.is_active_until and user.is_active_until > datetime.now(timezone.utc):
                # Если подписка уже активна, продлеваем ее
                user.is_active_until += timedelta(days=days)
            else:
                # Иначе, устанавливаем новую дату окончания
                user.is_active_until = datetime.now(timezone.utc) + timedelta(days=days)
            
            user.analyses_left = (user.analyses_left or 0) + analyses
            user.messages_left = (user.messages_left or 0) + messages
            user.subscription_source = source

            # Handle referral logic: if user was referred and this is their first payment, mark for payout
            if user.referred_by_id and not user.referral_payout_pending:
                user.referral_payout_pending = True
            
            await session.commit()

async def revoke_subscription(user_id: int) -> bool:
    """Revokes a user's subscription."""
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if not user or not user.is_active_until:
                return False  # Нечего отзывать

            user.is_active_until = None
            user.analyses_left = 0
            user.messages_left = 0
            await session.commit()
            return True

async def get_all_users() -> list[User]:
    """Получает всех пользователей из базы данных."""
    async with async_session() as session:
        result = await session.execute(select(User))
        return result.scalars().all()


async def get_subscribed_users() -> list[User]:
    """Получает всех пользователей с активной подпиской."""
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.is_active_until > now)
        )
        return result.scalars().all()


async def get_unsubscribed_users() -> list[User]:
    """Получает всех пользователей без активной подписки."""
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        result = await session.execute(
            select(User).where((User.is_active_until == None) | (User.is_active_until <= now))
        )
        return result.scalars().all()


async def get_user_by_username(username: str) -> User | None:
    """Finds a user by their username (case-insensitive)."""
    async with async_session() as session:
        # Убираем @, если он есть
        if username.startswith('@'):
            username = username[1:]
        
        result = await session.execute(
            select(User).where(func.lower(User.username) == username.lower())
        )
        return result.scalars().first()


async def set_ambassador_status(user_id: int, status: bool) -> bool:
    """Sets or unsets ambassador status for a user."""
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if not user:
                return False
            user.is_ambassador = status
            await session.commit()
            return True


async def get_all_ambassadors() -> list[User]:
    """Retrieves all users with ambassador status."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.is_ambassador == True)
        )
        return list(result.scalars().all())


async def get_referral_stats(ambassador_id: int) -> dict:
    """Returns referral statistics for a specific ambassador.

    Keys:
        total_referred:  Число пользователей, пришедших по ссылке (created with referred_by_id)
        pending_payouts: Число рефералов, у которых оплатa подтверждена и ждёт выплаты
        total_paid_referrals: Число рефералов с любой активной подпиской (для общей аналитики)
    """
    async with async_session() as session:
        # 1. Всего пришедших (по ссылке)
        total_ref_result = await session.execute(
            select(func.count(User.id)).where(
                User.referred_by_id == ambassador_id
            )
        )
        total_referred = total_ref_result.scalar_one()

        # 2. Ожидают выплаты (pending)
        pending_result = await session.execute(
            select(func.count(User.id)).where(
                User.referred_by_id == ambassador_id,
                User.referral_payout_pending == True
            )
        )
        pending_count = pending_result.scalar_one()

        # 3. Всего оплативших (имеют активную подписку)
        total_paid_result = await session.execute(
            select(func.count(User.id)).where(
                User.referred_by_id == ambassador_id,
                User.is_active_until != None
            )
        )
        total_paid_count = total_paid_result.scalar_one()

        return {
            "total_referred": total_referred,
            "pending_payouts": pending_count,
            "total_paid_referrals": total_paid_count,
        }


async def get_bulk_referral_stats(ambassador_ids: list[int]) -> dict[int, dict]:
    """Returns referral statistics for many ambassadors in one pass.

    The returned dict is keyed by ambassador_id and each value contains:
        total_referred        – users that came with this referral code
        pending_payouts       – first-time payers awaiting payout
        total_paid_referrals  – users with any active subscription
    Designed to minimise DB queries when there are many ambassadors.
    """
    if not ambassador_ids:
        return {}

    # Initialise result structure
    stats: dict[int, dict] = {
        amb_id: {
            "total_referred": 0,
            "pending_payouts": 0,
            "total_paid_referrals": 0,
        }
        for amb_id in ambassador_ids
    }

    async with async_session() as session:
        # 1. Total referred
        result = await session.execute(
            select(User.referred_by_id, func.count(User.id)).where(
                User.referred_by_id.in_(ambassador_ids)
            ).group_by(User.referred_by_id)
        )
        for amb_id, cnt in result.all():
            if amb_id in stats:
                stats[amb_id]["total_referred"] = cnt

        # 2. Pending payouts
        result = await session.execute(
            select(User.referred_by_id, func.count(User.id)).where(
                User.referred_by_id.in_(ambassador_ids),
                User.referral_payout_pending.is_(True),
            ).group_by(User.referred_by_id)
        )
        for amb_id, cnt in result.all():
            if amb_id in stats:
                stats[amb_id]["pending_payouts"] = cnt

        # 3. Total paid
        result = await session.execute(
            select(User.referred_by_id, func.count(User.id)).where(
                User.referred_by_id.in_(ambassador_ids),
                User.is_active_until.is_not(None),
            ).group_by(User.referred_by_id)
        )
        for amb_id, cnt in result.all():
            if amb_id in stats:
                stats[amb_id]["total_paid_referrals"] = cnt

    return stats


async def confirm_referral_payouts(ambassador_id: int) -> int:
    """Resets the pending payout status for an ambassador's referrals."""
    async with async_session() as session:
        async with session.begin():
            # Find users to update
            stmt = select(User).where(
                User.referred_by_id == ambassador_id,
                User.referral_payout_pending == True
            )
            results = await session.execute(stmt)
            users_to_update = results.scalars().all()
            
            count = 0
            for user in users_to_update:
                user.referral_payout_pending = False
                count += 1

            if count > 0:
                await session.commit()
            
            return count


async def get_bot_statistics() -> dict:
    """Retrieves general bot statistics."""
    async with async_session() as session:
        total_users = await session.execute(select(func.count(User.id)))
        
        active_subscriptions = await session.execute(
            select(func.count(User.id)).where(User.is_active_until > datetime.now(timezone.utc))
        )
        
        return {
            "total_users": total_users.scalar_one(),
            "active_subscriptions": active_subscriptions.scalar_one(),
        }

async def get_subscription_stats() -> dict:
    """Returns detailed subscription statistics, broken down by source."""
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        # Base query for all active subscriptions
        active_subs_query = select(User).where(User.is_active_until > now)
        active_subs_result = await session.execute(active_subs_query)
        active_subs = active_subs_result.scalars().all()

        total_active = len(active_subs)
        total_purchased = sum(1 for u in active_subs if u.subscription_source == 'purchased')
        total_granted = sum(1 for u in active_subs if u.subscription_source == 'granted')
        # For legacy users who got a sub before this field was added
        total_other = total_active - total_purchased - total_granted

        # New users in the last periods (based on when their sub was last updated)
        def _count_new_since(ts):
            count = 0
            for u in active_subs:
                if not u.updated_at:
                    continue
                # Make updated_at timezone-aware before comparing
                updated_at_aware = u.updated_at.replace(tzinfo=timezone.utc) if u.updated_at.tzinfo is None else u.updated_at
                if updated_at_aware >= ts:
                    count += 1
            return count

        new_24h = _count_new_since(now - timedelta(hours=24))
        new_48h = _count_new_since(now - timedelta(hours=48))
        new_7d = _count_new_since(now - timedelta(days=7))

        return {
            "total_active": total_active,
            "total_purchased": total_purchased,
            "total_granted": total_granted,
            "total_other": total_other,
            "new_24h": new_24h,
            "new_48h": new_48h,
            "new_7d": new_7d,
        }

async def get_pending_payouts_count() -> int:
    """Returns number of referred users awaiting payout across all ambassadors."""
    async with async_session() as session:
        result = await session.execute(
            select(func.count(User.id)).where(User.referral_payout_pending == True)
        )
        return result.scalar_one()


async def get_user_detailed_stats(user_id: int) -> dict:
    """Returns detailed stats about a single user for admin view."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return {}

        # Make sure timezone aware
        if user.is_active_until and user.is_active_until.tzinfo is None:
            user.is_active_until = user.is_active_until.replace(tzinfo=timezone.utc)

        stats = {
            "user": user,
            "subscription_active": user.is_active_until and user.is_active_until > datetime.now(timezone.utc),
            "active_until": user.is_active_until,
            "analyses_left": user.analyses_left,
            "messages_left": user.messages_left,
            "is_ambassador": user.is_ambassador,
        }

        if user.is_ambassador:
            stats.update(await get_referral_stats(user_id))
        return stats
