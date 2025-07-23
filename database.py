"""Database configuration and connection management."""

import os
from typing import AsyncGenerator

from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from models import User, Session, Task


# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/hd_lookism")

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
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session() as session:
        yield session


async def close_db() -> None:
    """Close database connection."""
    await engine.dispose()


async def add_user(user_id: int) -> None:
    """Add a new user to the database if they don't exist."""
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if not user:
                session.add(User(id=user_id))
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
    """Получает пользователя по его ID."""
    async with async_session() as session:
        user = await session.get(User, user_id)
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
