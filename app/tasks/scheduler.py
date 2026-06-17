import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.redis_client import get_redis
from app.models.db import ShipmentRecord, ShipmentStatus
from app.services.agiso import AgisoClient, PROCESSED_KEY_PREFIX, PROCESSED_TTL
from app.services.jiandaoyun import JiandaoyunClient
from app.services.order_processor import process_order
from app.services.notifier import alert_no_fuka
from app.core.config import get_settings
import json

logger = logging.getLogger(__name__)
settings = get_settings()

QUEUE_NAME = "queue:fuka_orders"


async def retry_pending_orders() -> None:
    """补偿任务：重新处理 pending/pending_manual 状态的订单"""
    logger.info("Scheduler: retry_pending_orders start")
    async with AsyncSessionLocal() as db:
        records = (await db.execute(
            select(ShipmentRecord).where(
                ShipmentRecord.status.in_([
                    ShipmentStatus.pending,
                    ShipmentStatus.pending_manual,
                ])
            )
        )).scalars().all()

    redis = await get_redis()
    for rec in records:
        # pending_manual 超过1小时重新告警
        if rec.status == ShipmentStatus.pending_manual:
            age = datetime.now(timezone.utc) - rec.updated_at.replace(tzinfo=timezone.utc)
            if age > timedelta(hours=1):
                await alert_no_fuka(rec.taobao_order_id)
            continue

        # pending 重新入队
        job = json.dumps({"tid": rec.taobao_order_id, "token": ""})
        await redis.lpush(QUEUE_NAME, job)
        logger.info("Scheduler: re-queued order %s", rec.taobao_order_id)

    logger.info("Scheduler: retry_pending_orders done, %d records", len(records))


async def repair_jdy_updates() -> None:
    """
    补偿任务：已发货但简道云可能未更新的记录（jdy_record_id 存在但状态疑问），
    尝试重新调用简道云更新接口。
    """
    logger.info("Scheduler: repair_jdy_updates start")
    jdy = JiandaoyunClient()
    async with AsyncSessionLocal() as db:
        records = (await db.execute(
            select(ShipmentRecord).where(
                ShipmentRecord.status == ShipmentStatus.shipped,
                ShipmentRecord.jdy_record_id.isnot(None),
                # 只处理最近48小时的已发货记录（兜底窗口）
                ShipmentRecord.updated_at >= datetime.now(timezone.utc) - timedelta(hours=48),
            )
        )).scalars().all()

    for rec in records:
        try:
            await jdy.mark_fuka_used(rec.jdy_record_id, rec.taobao_order_id)
        except Exception as e:
            logger.warning("repair_jdy_updates: failed for %s: %s", rec.taobao_order_id, e)

    logger.info("Scheduler: repair_jdy_updates done, %d records checked", len(records))
