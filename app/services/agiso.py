import hashlib
import time
import logging
import httpx
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

QUEUE_NAME = "queue:fuka_orders"
PROCESSED_KEY_PREFIX = "processed:order:"
PROCESSED_TTL = 7 * 24 * 3600  # 7天


def _sign(params: dict) -> str:
    """阿奇索签名：参数字典按key排序拼接后 MD5 大写"""
    sorted_str = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    return hashlib.md5(sorted_str.encode()).hexdigest().upper()


class AgisoClient:
    def __init__(self):
        self.app_id = settings.agiso_app_id
        self.app_secret = settings.agiso_app_secret
        self.base_url = settings.agiso_base_url

    def _build_params(self, method: str, extra: dict) -> dict:
        ts = str(int(time.time()))
        params = {
            "appId": self.app_id,
            "method": method,
            "timestamp": ts,
            **extra,
        }
        params["sign"] = _sign({**params, "appSecret": self.app_secret})
        return params

    async def get_orders(self, token: str, page_no: int = 1, page_size: int = 100) -> dict:
        """拉取待发货订单列表"""
        params = self._build_params("tmall.order.detail.get", {
            "token": token,
            "status": "WAIT_SELLER_SEND_GOODS",
            "pageNo": str(page_no),
            "pageSize": str(page_size),
        })
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/open/api", data=params)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("agiso get_orders response: %s", data)
            return data

    async def get_order_detail(self, token: str, tid: str) -> dict:
        """获取单个订单详情（含商品列表）"""
        params = self._build_params("tmall.order.detail.get", {
            "token": token,
            "tid": tid,
        })
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/open/api", data=params)
            resp.raise_for_status()
            return resp.json()

    async def ship_order(self, token: str, tid: str, delivery_content: str) -> dict:
        """虚拟发货：将副卡链接作为发货内容通知买家"""
        params = self._build_params("taobao.logistics.online.send", {
            "token": token,
            "tid": tid,
            "out_sid": tid,           # 虚拟商品用订单号作为运单号
            "company_code": "VIRTUAL", # 虚拟发货标识
            "remark": delivery_content,
        })
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/open/api", data=params)
            resp.raise_for_status()
            data = resp.json()
            logger.info("agiso ship_order tid=%s result: %s", tid, data)
            return data

    def verify_webhook_sign(self, payload: dict, received_sign: str) -> bool:
        expected = _sign({**payload, "appSecret": self.app_secret})
        return expected == received_sign.upper()
