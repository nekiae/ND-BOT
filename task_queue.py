"""Redis queue system for background task processing."""

import os
import json
import logging
import time
import asyncio
from typing import Optional, Dict, Any
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class TaskQueue:
    """Redis-based task queue for background processing."""
    
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.queue_name = "hd_lookism:tasks"
        self.redis: Optional[redis.Redis] = None
    
    async def connect(self) -> None:
        """Connect to Redis."""
        try:
            self.redis = redis.from_url(self.redis_url)
            await self.redis.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self.redis:
            await self.redis.close()
            logger.info("Disconnected from Redis")
    
    async def enqueue(self, session_id: int) -> None:
        """
        Add a session to the processing queue.
        
        Args:
            session_id: Session ID to process
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        task_data = {
            "session_id": session_id,
            "enqueued_at": str(int(time.time()))
        }
        
        await self.redis.lpush(self.queue_name, json.dumps(task_data))
        logger.info(f"Enqueued session {session_id} for processing")
    
    async def dequeue(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """
        Get next task from queue (blocking).
        
        Args:
            timeout: Timeout in seconds
            
        Returns:
            Task data or None if timeout
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        try:
            result = await self.redis.brpop(self.queue_name, timeout=timeout)
            if result:
                _, task_json = result
                return json.loads(task_json)
            return None
        except Exception as e:
            logger.error(f"Error dequeuing task: {e}")
            return None
    
    async def get_queue_size(self) -> int:
        """Get current queue size."""
        if not self.redis:
            return 0
        
        try:
            return await self.redis.llen(self.queue_name)
        except Exception as e:
            logger.error(f"Error getting queue size: {e}")
            return 0


# Global queue instance
task_queue = TaskQueue()


async def init_queue() -> None:
    """Initialize the task queue."""
    await task_queue.connect()


async def close_queue() -> None:
    """Close the task queue."""
    await task_queue.disconnect()
