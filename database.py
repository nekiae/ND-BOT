"""Database configuration and connection management."""

import os
from typing import AsyncGenerator

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
        return user.is_active_until > datetime.utcnow()

async def give_subscription_to_user(user_id: int, days: int = 30, analyses: int = 3, messages: int = 200) -> None:
    """Grant or extend a subscription for a user."""
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if not user:
                user = User(id=user_id)
                session.add(user)
            
            if user.is_active_until and user.is_active_until > datetime.utcnow():
                # Если подписка уже активна, продлеваем ее
                user.is_active_until += timedelta(days=days)
            else:
                # Иначе, устанавливаем новую дату окончания
                user.is_active_until = datetime.utcnow() + timedelta(days=days)
            
            user.analyses_left += analyses
            user.messages_left += messages
            
            await session.commit()
