import asyncio
import logging
import httpx
from datetime import datetime, timezone
from app.core.config import get_settings
from app.models.schemas import JdyRecord

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://api.jiandaoyun.com/api/v5"

# 简道云偶发慢响应，read 给到 30s；连接/写入/连接池各自较短避免空等
JDY_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

# 这些异常视为瞬时网络抖动，可安全重试
_RETRYABLE = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


class JiandaoyunClient:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {settings.jdy_api_key}",
            "Content-Type": "application/json",
        }
        self.app_id = settings.jdy_app_id
        self.entry_id = settings.jdy_entry_id

    async def _post(self, path: str, payload: dict, *, retries: int = 2) -> dict:
        """统一 POST 请求：30s read timeout + 瞬时错误指数退避重试。

        retries=2 表示首次失败后最多再试 2 次（共 3 次请求），
        退避间隔 1s、2s。非瞬时错误（如 4xx/5xx 业务错误）不重试。
        """
        url = f"{BASE_URL}{path}"
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=JDY_TIMEOUT) as client:
                    resp = await client.post(url, headers=self.headers, json=payload)
                    resp.raise_for_status()
                    return resp.json()
            except _RETRYABLE as e:
                last_exc = e
                if attempt < retries:
                    wait = 2 ** attempt  # 1s, 2s
                    logger.warning(
                        "JDY %s failed (attempt %d/%d): %s, retry in %ss",
                        path, attempt + 1, retries + 1, type(e).__name__, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    raise
        # 理论上不会走到
        raise last_exc  # type: ignore[misc]

    async def list_fields(self) -> dict:
        """查询表单字段结构，首次部署用于发现 widget ID"""
        data = await self._post(
            "/app/entry/widget/list",
            {"app_id": self.app_id, "entry_id": self.entry_id},
        )
        logger.info("JDY form fields: %s", data)
        return data

    async def get_available_fuka(self) -> JdyRecord | None:
        """
        查询满足条件的副卡：
          - 副卡售出状态 = 副卡未售
          - 售卖开关 = 开售
          - 副卡回收日期在 [now-24h, now] 区间内（距今24小时内回收过）
        """
        now = datetime.now(timezone.utc)
        expire_start = datetime.fromtimestamp(now.timestamp() - 86400, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M"
        )
        expire_end = now.strftime("%Y-%m-%dT%H:%M")

        payload = {
            "app_id": self.app_id,
            "entry_id": self.entry_id,
            "limit": 1,
            "filter": {
                "rel": "and",
                "cond": [
                    {
                        "field": settings.jdy_field_status,
                        "type": "text",
                        "method": "eq",
                        "value": [settings.jdy_status_available],
                    },
                    {
                        "field": settings.jdy_field_sale_switch,
                        "type": "text",
                        "method": "eq",
                        "value": [settings.jdy_status_on_sale],
                    },
                    {
                        "field": settings.jdy_field_expire,
                        "type": "datetime",
                        "method": "range",
                        "value": [expire_start, expire_end],
                    },
                ],
            },
        }

        logger.debug("JDY get_available_fuka payload: %s", payload)

        data = await self._post("/app/entry/data/list", payload)

        records = data.get("data", [])
        logger.info("JDY available fuka count: %d", len(records))
        if not records:
            return None

        row = records[0]
        link_field = row.get(settings.jdy_field_link)
        link = link_field.get("value", "") if isinstance(link_field, dict) else str(link_field or "")

        return JdyRecord(
            record_id=row["_id"],
            link=link,
            expire_time=str(row.get(settings.jdy_field_expire, "")),
            raw=row,
        )

    async def mark_fuka_used(self, record_id: str) -> bool:
        """将副卡状态更新为已售"""
        payload = {
            "app_id": self.app_id,
            "entry_id": self.entry_id,
            "data_id": record_id,
            "data": {
                settings.jdy_field_status: {"value": settings.jdy_status_used},
            },
            "is_start_trigger": False,
        }
        result = await self._post("/app/entry/data/update", payload)
        logger.info("JDY mark_used record=%s result=%s", record_id, result)
        return True

    async def rollback_fuka(self, record_id: str) -> None:
        """发货失败时将副卡状态回滚为未售"""
        payload = {
            "app_id": self.app_id,
            "entry_id": self.entry_id,
            "data_id": record_id,
            "data": {
                settings.jdy_field_status: {"value": settings.jdy_status_available},
                settings.jdy_field_order_id: {"value": ""},
            },
            "is_start_trigger": False,
        }
        try:
            await self._post("/app/entry/data/update", payload)
            logger.info("JDY rollback_fuka record=%s done", record_id)
        except Exception as e:
            logger.error("JDY rollback_fuka failed for %s: %s", record_id, e)
