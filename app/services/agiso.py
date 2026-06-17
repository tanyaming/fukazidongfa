import hashlib
import time
import logging
import httpx
from urllib.parse import urlencode
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

QUEUE_NAME = "queue:fuka_orders"
PROCESSED_KEY_PREFIX = "processed:order:"
PROCESSED_TTL = 7 * 24 * 3600  # 7天


def _sign_v2(params: dict, app_secret: str) -> str:
    """新版 API 签名：appSecret + sortedKV + appSecret → MD5 小写"""
    sorted_str = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    raw = f"{app_secret}{sorted_str}{app_secret}"
    return hashlib.md5(raw.encode()).hexdigest().lower()


def _sign_v1(params: dict, app_secret: str) -> str:
    """老版签名：sortedKV + appSecret → MD5 大写（用于 webhook 推送验证）"""
    sorted_str = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    raw = f"{sorted_str}{app_secret}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def sign_webhook(params: dict, received_sign: str, app_secret: str) -> bool:
    """验证 Webhook 推送签名（老版 v1）"""
    expected = _sign_v1(params, app_secret)
    return expected.upper() == received_sign.upper()


class AgisoClient:
    def __init__(self):
        self.app_secret = settings.agiso_app_secret
        self.base_url = settings.agiso_base_url

    def _build_request(self, url_path: str, params: dict, access_token: str) -> tuple[str, dict, str]:
        """构建新版 API 请求：返回 (url, headers, body)"""
        ts = str(int(time.time()))
        body_params = {
            **params,
            "timestamp": ts,
        }
        body_params["sign"] = _sign_v2(body_params, self.app_secret)
        body = urlencode(body_params)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "ApiVersion": "1",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        url = f"{self.base_url}{url_path}"
        return url, headers, body

    async def get_order_detail(self, access_token: str, tid: str) -> dict:
        """获取订单详情"""
        if not access_token:
            raise ValueError("access_token is required")
        url, headers, body = self._build_request("/Order/Detail", {"tid": tid}, access_token)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, content=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("agiso get_order_detail tid=%s response: %s", tid, data)
            return data

    async def get_order_list(
        self, access_token: str, status: str = "WAIT_SELLER_SEND_GOODS",
        page_no: int = 1, page_size: int = 100,
    ) -> dict:
        """拉取订单列表"""
        if not access_token:
            raise ValueError("access_token is required")
        url, headers, body = self._build_request("/Order/List", {
            "status": status,
            "pageNo": str(page_no),
            "pageSize": str(page_size),
        }, access_token)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, content=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("agiso get_order_list response: %s", data)
            return data

    async def ship_order(self, access_token: str, tid: str, delivery_content: str) -> dict:
        """虚拟发货"""
        if not access_token:
            raise ValueError("access_token is required")
        url, headers, body = self._build_request("/Order/DummySend", {
            "tid": tid,
            "remark": delivery_content,
        }, access_token)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, content=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info("agiso ship_order tid=%s result: %s", tid, data)
            return data
