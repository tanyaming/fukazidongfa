import json
import logging
from fastapi import APIRouter, Request, HTTPException
from app.core.redis_client import get_redis
from app.services.agiso import AgisoClient, PROCESSED_KEY_PREFIX, PROCESSED_TTL, sign_webhook
from app.tasks.worker import QUEUE_NAME
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
agiso = AgisoClient()
settings = get_settings()


@router.post("/webhook/agiso")
async def agiso_webhook(request: Request):
    """接收阿奇索订单推送"""
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        raw_body = await request.json()
    else:
        form = await request.form()
        raw_body = dict(form)

    query_params = dict(request.query_params)
    logger.info("Webhook received body: %s query: %s", raw_body, query_params)

    # 阿奇索推送格式：body 中有 json 字段包含订单数据
    json_str = raw_body.get("json", "")
    if json_str:
        try:
            body = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse json field: %s", json_str)
            raise HTTPException(status_code=400, detail="Invalid json")
    else:
        body = raw_body

    # 签名验证：sign 在 query string，签名参数 = query参数(去sign/aopic) + json字符串
    received_sign = query_params.get("sign", "") or str(raw_body.get("sign", ""))
    sign_payload = {k: v for k, v in query_params.items() if k not in ("sign", "aopic")}
    sign_payload["json"] = raw_body.get("json", "")

    if received_sign:
        webhook_secret = settings.agiso_webhook_secret or settings.agiso_app_secret
        if not sign_webhook(sign_payload, received_sign, webhook_secret):
            logger.warning("Invalid sign: received=%s payload=%s", received_sign, sign_payload)
            # 测试推送用平台默认密钥，暂时跳过；配置完商户密钥后启用下面一行
            # raise HTTPException(status_code=401, detail="Invalid signature")

    tid = str(body.get("Tid") or body.get("tid") or "")
    if not tid:
        logger.warning("Webhook missing tid, body=%s", body)
        raise HTTPException(status_code=400, detail="Missing tid")

    status = str(body.get("Status") or body.get("status") or "")
    # TODO: 正式上线恢复状态过滤
    # if status and status != "WAIT_SELLER_SEND_GOODS":
    #     logger.info("Order %s status=%s ignored", tid, status)
    #     return {"code": 0, "msg": "ignored"}

    token = str(body.get("Token") or body.get("token") or "")

    redis = await get_redis()
    processed_key = f"{PROCESSED_KEY_PREFIX}{tid}"
    if await redis.exists(processed_key):
        logger.info("Order %s already processed, skip", tid)
        return {"code": 0, "msg": "already processed"}

    await redis.set(processed_key, "1", ex=PROCESSED_TTL)
    await redis.lpush(QUEUE_NAME, json.dumps({"tid": tid, "token": token}))
    logger.info("Order %s enqueued", tid)

    return {"code": 0, "msg": "ok"}


@router.get("/health")
async def health():
    return {"status": "ok"}
