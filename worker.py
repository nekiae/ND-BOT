"""Background worker for processing facial analysis tasks."""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session, create_db_and_tables
from models import Session, Task, SessionStatus, TaskStatus
from task_queue import task_queue
from analyzers.client import FacePlusPlusClient, AILabClient, DeepSeekClient
from analyzers.metrics import extract_all_metrics
from analyzers.lookism_metrics import compute_all as compute_geo_metrics
from analyzers.report_generator import create_report_for_user
import httpx

logger = logging.getLogger(__name__)


class AnalysisWorker:
    """Background worker for facial analysis processing."""
    
    def __init__(self):
        self.facepp_client = FacePlusPlusClient()
        self.ailab_client = AILabClient()
        self.deepseek_client = DeepSeekClient()
        self.running = False
    
    async def download_photo(self, file_id: str, bot_token: str) -> bytes:
        """Download photo from Telegram servers."""
        async with httpx.AsyncClient() as client:
            # Get file path
            file_response = await client.get(
                f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
            )
            file_data = file_response.json()
            
            if not file_data.get("ok"):
                raise Exception(f"Failed to get file info: {file_data}")
            
            file_path = file_data["result"]["file_path"]
            
            # Download file
            download_response = await client.get(
                f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
            )
            download_response.raise_for_status()
            
            return download_response.content
    
    async def process_session(self, session_id: int) -> None:
        """Process a single analysis session."""
        async for db_session in get_session():
            try:
                # Get session from database
                session = await db_session.get(Session, session_id)
                if not session:
                    logger.error(f"Session {session_id} not found")
                    return
                
                # Update session status
                session.status = SessionStatus.PROCESSING
                await db_session.commit()
                
                # Create task record
                task = Task(session_id=session_id, status=TaskStatus.PROCESSING, started_at=datetime.utcnow())
                db_session.add(task)
                await db_session.commit()
                
                logger.info(f"Processing session {session_id}")
                
                # Download photos
                bot_token = os.getenv("BOT_TOKEN")
                front_photo = await self.download_photo(session.front_file_id, bot_token)
                profile_photo = await self.download_photo(session.profile_file_id, bot_token)
                
                # Analyze with Face++
                logger.info("Analyzing with Face++...")
                facepp_result = await self.facepp_client.analyze_face(front_photo)
                
                # Analyze with AILab
                logger.info("Analyzing with AILab...")
                ailab_result = await self.ailab_client.analyze_face(front_photo)
                
                # Extract metrics (beauty + 106-landmark metrics)
                logger.info("Extracting metrics...")
                metrics = extract_all_metrics(facepp_result, ailab_result)

                # Extra geometric metrics from 83-point Face++ landmarks
                try:
                    face_landmarks = facepp_result["faces"][0].get("landmark", {})
                    if face_landmarks:
                        geo_metrics = compute_geo_metrics(face_landmarks)
                        metrics.update(geo_metrics)
                except Exception as geo_err:
                    logger.warning(f"Failed to compute geo metrics: {geo_err}")
                
                # Generate report with DeepSeek
                logger.info("Generating report...")
                try:
                    report_text = await create_report_for_user(metrics)
                except Exception as report_err:
                    logger.error(f"Failed to generate report: {report_err}")
                    report_text = "Произошла ошибка при создании отчета. Попробуйте позже."
                
                # Save results
                session.result_json = {
                    "metrics": metrics,
                    "report": report_text,
                    "facepp_raw": facepp_result,
                    "ailab_raw": ailab_result
                }
                session.status = SessionStatus.DONE
                session.finished_at = datetime.utcnow()
                
                task.status = TaskStatus.DONE
                task.finished_at = datetime.utcnow()
                
                await db_session.commit()
                
                logger.info(f"Successfully processed session {session_id}")
                
            except Exception as e:
                logger.error(f"Error processing session {session_id}: {e}")
                
                # Mark as failed
                if 'session' in locals():
                    session.status = SessionStatus.FAILED
                    await db_session.commit()
                
                if 'task' in locals():
                    task.status = TaskStatus.FAILED
                    task.error_message = str(e)
                    task.finished_at = datetime.utcnow()
                    await db_session.commit()
    
    async def run(self) -> None:
        """Main worker loop."""
        logger.info("Starting analysis worker...")
        self.running = True
        
        while self.running:
            try:
                # Get next task from queue
                task_data = await task_queue.dequeue(timeout=5)
                
                if task_data:
                    session_id = task_data["session_id"]
                    await self.process_session(session_id)
                
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(1)
    
    def stop(self) -> None:
        """Stop the worker."""
        logger.info("Stopping analysis worker...")
        self.running = False


async def main():
    """Main worker entry point."""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Initialize database
    await create_db_and_tables()
    
    # Initialize queue
    await task_queue.connect()
    
    # Start worker
    worker = AnalysisWorker()
    
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    finally:
        worker.stop()
        await task_queue.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
