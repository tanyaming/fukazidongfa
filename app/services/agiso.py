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


def _make_query_string(params: dict) -> str:
    """按 ASCII 排序拼接为 key=value&key=value（空值也参与）"""
    return "&".join(f"{k}={v}" for k, v in sorted(params.items()))


def _sign(params: dict, secret: str) -> str:
    """签名：secret + sorted_querystring + secret → MD5 32位大写"""
    qs = _make_query_string({k: v for k, v in params.items() if k != "sign"})
    raw = f"{secret}{qs}{secret}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def sign_webhook(params: dict, received_sign: str, app_secret: str) -> bool:
    """验证 Webhook 推送签名"""
    expected = _sign(params, app_secret)
    match = expected == received_sign.upper()
    if not match:
        logger.debug("Sign mismatch: expected=%s received=%s qs=%s",
                     expected, received_sign.upper(), _make_query_string(params))
    return match


class AgisoClient:
    def __init__(self):
        self.app_secret = settings.agiso_app_secret
        self.base_url = settings.agiso_base_url

    def _build_request(self, url_path: str, params: dict, access_token: str) -> tuple[str, dict, str]:
        """构建 API 请求"""
        body_params = {**params, "timestamp": str(int(time.time()))}
        body_params["sign"] = _sign(body_params, self.app_secret)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "ApiVersion": "1",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return f"{self.base_url}{url_path}", headers, urlencode(body_params)

    async def get_order_detail(self, access_token: str, tid: str) -> dict:
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
