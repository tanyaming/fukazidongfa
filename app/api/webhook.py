import json
import logging
from fastapi import APIRouter, Request, HTTPException
from app.core.redis_client import get_redis
from app.services.agiso import AgisoClient, PROCESSED_KEY_PREFIX, PROCESSED_TTL
from app.tasks.worker import QUEUE_NAME

logger = logging.getLogger(__name__)
router = APIRouter()
agiso = AgisoClient()


@router.post("/webhook/agiso")
async def agiso_webhook(request: Request):
    """接收阿奇索订单推送（form-encoded body，sign 在 query string）"""
    content_type = request.headers.get("content-type", "")

    # 阿奇索推送为 form-encoded，也兼容 JSON
    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    logger.info("Webhook received body: %s query: %s", body, dict(request.query_params))

    # sign 优先从 query string 取，其次从 body 取
    received_sign = (
        request.query_params.get("sign")
        or body.pop("sign", "")
        or request.headers.get("X-Sign", "")
    )

    # 签名验证（有 sign 才验，调试阶段可注释掉）
    if received_sign and not agiso.verify_webhook_sign(dict(body), received_sign):
        logger.warning("Invalid sign: received=%s body=%s", received_sign, body)
        raise HTTPException(status_code=401, detail="Invalid signature")

    tid = str(body.get("tid") or body.get("orderId") or body.get("oid") or "")
    if not tid:
        logger.warning("Webhook missing tid, body=%s", body)
        raise HTTPException(status_code=400, detail="Missing tid")

    status = str(body.get("status") or body.get("tradeStatus") or "")
    if status and status not in ("WAIT_SELLER_SEND_GOODS", ""):
        logger.info("Order %s status=%s ignored", tid, status)
        return {"code": 0, "msg": "ignored"}

    token = str(body.get("token") or "")

    redis = await get_redis()
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
