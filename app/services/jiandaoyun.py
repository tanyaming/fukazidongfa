import logging
import httpx
from datetime import datetime, timezone
from app.core.config import get_settings
from app.models.schemas import JdyRecord

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://api.jiandaoyun.com/api/v5"


class JiandaoyunClient:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {settings.jdy_api_key}",
            "Content-Type": "application/json",
        }
        self.app_id = settings.jdy_app_id
        self.entry_id = settings.jdy_entry_id

    async def list_fields(self) -> dict:
        """查询表单字段结构，首次部署用于发现 widget ID"""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{BASE_URL}/app/entry/widget/list",
                headers=self.headers,
                json={"app_id": self.app_id, "entry_id": self.entry_id},
            )
            if not resp.is_success:
                logger.warning("JDY list_fields failed %s: %s", resp.status_code, resp.text)
                resp.raise_for_status()
            data = resp.json()
            logger.info("JDY form fields: %s", data)
            return data

    async def get_available_fuka(self) -> JdyRecord | None:
        """
        查询满足条件的副卡（FIFO 取第一条）:
          - 副卡售出状态 == 副卡未售
          - 副卡回收日期在未来 24 小时内（距此刻 <=24h）
        """
        now = datetime.now(timezone.utc)
        # 回收日期区间：[now, now+24h]（过期前24小时内有效）
        expire_start = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        expire_end_ts = now.timestamp() + 86400
        expire_end = datetime.fromtimestamp(expire_end_ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

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
                        "field": settings.jdy_field_expire,
                        "type": "datetime",
                        "method": "range",
                        "value": [expire_start, expire_end],
                    },
                ],
            },
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{BASE_URL}/app/entry/data/list",
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        records = data.get("data", [])
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

    async def mark_fuka_used(self, record_id: str, taobao_order_id: str) -> bool:
        """将副卡状态更新为已售，并写入关联订单号"""
        payload = {
            "app_id": self.app_id,
            "entry_id": self.entry_id,
            "data_id": record_id,
            "data": {
                settings.jdy_field_status: {"value": settings.jdy_status_used},
                settings.jdy_field_order_id: {"value": taobao_order_id},
            },
            "is_start_trigger": False,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{BASE_URL}/app/entry/data/update",
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info("JDY mark_used record=%s order=%s result=%s", record_id, taobao_order_id, result)
            return True
