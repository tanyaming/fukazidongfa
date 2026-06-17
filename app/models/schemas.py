from pydantic import BaseModel
from typing import Any


class AgisoOrderItem(BaseModel):
    sku_id: str | None = None
    outer_sku_id: str | None = None  # 商家编码
    cid: str | None = None           # 商品类目 ID
    title: str | None = None
    num_iid: str | None = None


class AgisoOrder(BaseModel):
    tid: str                          # 淘宝订单号
    status: str | None = None
    buyer_nick: str | None = None
    orders: list[AgisoOrderItem] = []
    raw: dict[str, Any] = {}


class AgisoWebhookPayload(BaseModel):
    topic: str | None = None
    status: str | None = None
    tid: str
    seller_nick: str | None = None
    extra: dict[str, Any] = {}


class JdyRecord(BaseModel):
    record_id: str
    link: str
    expire_time: str | None = None
    raw: dict[str, Any] = {}
