import asyncio
import json
import logging
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.redis_client import get_redis
from app.services.agiso import AgisoClient
from app.services.jiandaoyun import JiandaoyunClient
from app.services.order_processor import process_order
from app.utils.lock import RedisLock

logger = logging.getLogger(__name__)
settings = get_settings()

QUEUE_NAME = "queue:fuka_orders"


async def handle_job(job: dict) -> None:
    tid = job.get("tid")
    token = job.get("token", "")
    if not tid:
        logger.warning("Job missing tid: %s", job)
        return

    redis = await get_redis()
    lock = RedisLock(redis, f"order:{tid}", ttl=120)
    if not await lock.acquire():
        logger.info("Order %s is being processed by another worker, skip", tid)
        return

    try:
        async with AsyncSessionLocal() as db:
            await process_order(
                tid=tid,
                token=token,
                db=db,
                agiso=AgisoClient(),
                jdy=JiandaoyunClient(),
            )
    finally:
        await lock.release()


async def run_worker() -> None:
    logger.info("Worker started, listening on %s", QUEUE_NAME)
    redis = await get_redis()
    while True:
        try:
            # BRPOP 阻塞等待，超时 5 秒后继续循环
            item = await redis.brpop(QUEUE_NAME, timeout=5)
            if item is None:
                continue
            _, raw = item
            job = json.loads(raw)
            asyncio.create_task(handle_job(job))
        except asyncio.CancelledError:
            logger.info("Worker cancelled, shutting down")
            break
        except Exception as e:
            logger.exception("Worker error: %s", e)
            await asyncio.sleep(1)
