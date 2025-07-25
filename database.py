"""Database configuration and connection management."""

import os
from typing import AsyncGenerator

from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy import text, TIMESTAMP
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column
from sqlmodel import SQLModel, select, func

from models import User, Session, Task


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
    """Runs raw SQL to add new referral-related columns if they are missing."""
    sql_statements = [
        "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS is_ambassador BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS referred_by_id BIGINT;",
        "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS referral_payout_pending BOOLEAN DEFAULT FALSE;"
    ]
    for stmt in sql_statements:
        await conn.execute(text(stmt))

async def create_db_and_tables() -> None:
    """Create database tables."""
    async with engine.begin() as conn:
        logger.info("Creating database tables if they do not exist…")
        await conn.run_sync(SQLModel.metadata.create_all)
        # Ensure new columns exist for referral system
        await _ensure_referral_columns(conn)
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

async def decrement_user_analyses(user_id: int):
    """Уменьшает количество оставшихся анализов пользователя на 1."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user and user.analyses_left > 0:
            user.analyses_left -= 1
            await session.commit()


async def give_subscription_to_user(user_id: int, days: int = 30, analyses: int = 2, messages: int = 200) -> None:
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
            
            user.analyses_left += analyses
            user.messages_left += messages

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
        return list(result.scalars().all())


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
    """Gets referral statistics for a specific ambassador."""
    async with async_session() as session:
        # Count referrals pending payout
        pending_result = await session.execute(
            select(func.count(User.id)).where(
                User.referred_by_id == ambassador_id,
                User.referral_payout_pending == True
            )
        )
        pending_count = pending_result.scalar_one()

        # Count total paid referrals (have an active subscription)
        total_paid_result = await session.execute(
            select(func.count(User.id)).where(
                User.referred_by_id == ambassador_id,
                User.is_active_until != None
            )
        )
        total_paid_count = total_paid_result.scalar_one()

        return {
            "pending_payouts": pending_count,
            "total_paid_referrals": total_paid_count
        }


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
