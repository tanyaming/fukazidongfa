import json
import logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from app.core.redis_client import get_redis
from app.services.agiso import AgisoClient, PROCESSED_KEY_PREFIX, PROCESSED_TTL
from app.tasks.worker import QUEUE_NAME

logger = logging.getLogger(__name__)
router = APIRouter()
agiso = AgisoClient()


@router.post("/webhook/agiso")
async def agiso_webhook(request: Request, background_tasks: BackgroundTasks):
    """接收阿奇索订单推送"""
    body = await request.json()
    logger.debug("Webhook received: %s", body)

    # 签名验证
    received_sign = request.headers.get("X-Sign", body.pop("sign", ""))
    if received_sign and not agiso.verify_webhook_sign(body, received_sign):
        raise HTTPException(status_code=401, detail="Invalid signature")

    tid = str(body.get("tid") or body.get("orderId") or "")
    if not tid:
        raise HTTPException(status_code=400, detail="Missing tid")

    status = body.get("status", "")
    # 只处理等待卖家发货状态
    if status and status != "WAIT_SELLER_SEND_GOODS":
        return {"code": 0, "msg": "ignored"}

    token = body.get("token", "")

    redis = await get_redis()

    # 幂等：已处理的订单不重复入队
    processed_key = f"{PROCESSED_KEY_PREFIX}{tid}"
    if await redis.exists(processed_key):
        logger.info("Order %s already processed, skip", tid)
        return {"code": 0, "msg": "already processed"}

    await redis.set(processed_key, "1", ex=PROCESSED_TTL)
    job = json.dumps({"tid": tid, "token": token})
    await redis.lpush(QUEUE_NAME, job)
    logger.info("Order %s enqueued", tid)

    return {"code": 0, "msg": "ok"}


@router.get("/health")
async def health():
    return {"status": "ok"}
