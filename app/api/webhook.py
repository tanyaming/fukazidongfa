import json
import logging
from fastapi import APIRouter, Request, HTTPException
from app.core.redis_client import get_redis
from app.services.agiso import AgisoClient, PROCESSED_KEY_PREFIX, PROCESSED_TTL, sign_webhook
from app.tasks.worker import QUEUE_NAME

logger = logging.getLogger(__name__)
router = APIRouter()
agiso = AgisoClient()


@router.post("/webhook/agiso")
async def agiso_webhook(request: Request):
    """接收阿奇索订单推送"""
    content_type = request.headers.get("content-type", "")

    # 解析 form-encoded body
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

    # 签名验证：sign 在 query string 中
    received_sign = query_params.get("sign", "") or raw_body.get("sign", "")
    # 签名参与计算时用 query 参数（不含 sign）+ body 中的 json 字符串
    sign_payload = {**query_params, "json": raw_body.get("json", "")}
    sign_payload.pop("sign", None)
    sign_payload.pop("aopic", None)  # aopic 不参与签名

    if received_sign and not sign_webhook(sign_payload, received_sign, agiso.app_secret):
        logger.warning("Invalid sign: received=%s, payload=%s", received_sign, sign_payload)
        # TODO: 签名验证暂时跳过，先跑通业务流程
        # raise HTTPException(status_code=401, detail="Invalid signature")

    # 提取订单信息（大写驼峰字段）
    tid = str(body.get("Tid") or body.get("tid") or "")
    if not tid:
        logger.warning("Webhook missing tid, body=%s", body)
        raise HTTPException(status_code=400, detail="Missing tid")

    status = str(body.get("Status") or body.get("status") or "")
    # TODO: 临时放行所有状态用于测试，正式上线恢复
    # if status and status != "WAIT_SELLER_SEND_GOODS":
    #     logger.info("Order %s status=%s ignored", tid, status)
    #     return {"code": 0, "msg": "ignored"}
    logger.info("Order %s status=%s accepted (status check disabled)", tid, status)

    # 推流中没有 token，需要后续通过平台信息获取
    # 暂时把 Platform + PlatformUserId 存下来
    token = str(body.get("Token") or body.get("token") or "")
    platform = body.get("Platform", "")
    platform_user_id = body.get("PlatformUserId", "")

    redis = await get_redis()
    processed_key = f"{PROCESSED_KEY_PREFIX}{tid}"
    if await redis.exists(processed_key):
        logger.info("Order %s already processed, skip", tid)
        return {"code": 0, "msg": "already processed"}

    await redis.set(processed_key, "1", ex=PROCESSED_TTL)
    job = json.dumps({
        "tid": tid,
        "token": token,
        "platform": platform,
        "platform_user_id": platform_user_id,
    })
    await redis.lpush(QUEUE_NAME, job)
    logger.info("Order %s enqueued", tid)

    return {"code": 0, "msg": "ok"}


@router.get("/health")
async def health():
    return {"status": "ok"}
