import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.api.webhook import router as webhook_router
from app.core.config import get_settings
from app.core.database import engine, Base
from app.tasks.worker import run_worker
from app.tasks.scheduler import retry_pending_orders, repair_jdy_updates
from app.services.jiandaoyun import JiandaoyunClient

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task, _scheduler

    # 建表（带重试，等待 MySQL 就绪）
    for attempt in range(10):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables ensured")
            break
        except Exception as e:
            if attempt >= 9:
                raise
            logger.warning("DB not ready (attempt %d/10): %s — retrying in 3s", attempt + 1, e)
            await asyncio.sleep(3)

    # 打印简道云字段结构（方便首次配置）
    try:
        jdy = JiandaoyunClient()
        fields = await jdy.list_fields()
        logger.info("=== JDY form fields (copy widget IDs to .env) ===\n%s", fields)
    except Exception as e:
        logger.warning("Could not fetch JDY fields: %s", e)

    # 启动 worker 协程
    _worker_task = asyncio.create_task(run_worker())

    # 启动定时任务
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        retry_pending_orders,
        "interval",
        minutes=settings.scheduler_interval_minutes,
        id="retry_pending",
    )
    _scheduler.add_job(
        repair_jdy_updates,
        "interval",
        minutes=30,
        id="repair_jdy",
    )
    _scheduler.start()
    logger.info("Scheduler started, interval=%d min", settings.scheduler_interval_minutes)

    yield

    # 关闭
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    if _scheduler:
        _scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="副卡自动发货服务",
    description="淘宝订单副卡自动发货后端，对接阿奇索开放平台与简道云",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)
