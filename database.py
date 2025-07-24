"""Database configuration and connection management."""

import os
from typing import AsyncGenerator

from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import TIMESTAMP
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


async def create_db_and_tables() -> None:
    """Create database tables."""
    async with engine.begin() as conn:
        # ВНИМАНИЕ: Эта строка удалит все существующие данные перед созданием новых таблиц.
        # Это необходимо для применения изменений схемы, таких как переход на BigInteger.
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session() as session:
        yield session


async def close_db() -> None:
    """Close database connection."""
    await engine.dispose()


async def add_user(user_id: int, username: str | None = None) -> None:
    """Add a new user or update their username."""
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if not user:
                session.add(User(id=user_id, username=username))
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


async def give_subscription_to_user(user_id: int, days: int = 30, analyses: int = 3, messages: int = 200) -> None:
    """Grant or extend a subscription for a user."""
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
