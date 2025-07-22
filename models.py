"""Database models for HD | Lookism bot."""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from sqlmodel import SQLModel, Field, JSON, Column


class SessionStatus(str, Enum):
    """Session processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class TaskStatus(str, Enum):
    """Task processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class User(SQLModel, table=True):
    """User model for subscription tracking."""
    
    __tablename__ = "users"
    
    id: int = Field(primary_key=True)  # Telegram user ID
    is_active_until: Optional[datetime] = Field(default=None)
    analyses_left: int = Field(default=0)
    messages_left: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Session(SQLModel, table=True):
    """Photo analysis session."""
    
    __tablename__ = "sessions"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    front_file_id: Optional[str] = Field(default=None)
    profile_file_id: Optional[str] = Field(default=None)
    status: SessionStatus = Field(default=SessionStatus.PENDING)
    result_json: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = Field(default=None)


class Task(SQLModel, table=True):
    """Background task for processing."""
    
    __tablename__ = "tasks"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="sessions.id")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
