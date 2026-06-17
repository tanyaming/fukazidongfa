import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.db import ShipmentRecord, ShipmentStatus, FukaProductRule
from app.models.schemas import AgisoOrder, AgisoOrderItem
from app.services.agiso import AgisoClient
from app.services.jiandaoyun import JiandaoyunClient
from app.services.notifier import alert_no_fuka, alert_ship_failed

logger = logging.getLogger(__name__)

MAX_RETRY = 3


def _parse_order_items(raw: dict) -> list[AgisoOrderItem]:
    """从阿奇索订单详情响应中解析商品列表"""
    orders_raw = raw.get("orders") or raw.get("data", {}).get("orders") or []
    if isinstance(orders_raw, dict):
        orders_raw = orders_raw.get("order", [])
    items = []
    for o in orders_raw:
        items.append(AgisoOrderItem(
            sku_id=str(o.get("sku_id") or ""),
            outer_sku_id=str(o.get("outer_sku_id") or o.get("outer_iid") or ""),
            cid=str(o.get("cid") or ""),
            title=str(o.get("title") or ""),
            num_iid=str(o.get("num_iid") or ""),
        ))
    return items


async def is_fuka_order(order: AgisoOrder, db: AsyncSession) -> bool:
    """检查订单中是否包含副卡商品（查 fuka_product_rules 表）"""
    rules = (await db.execute(
        select(FukaProductRule).where(FukaProductRule.enabled == 1)
    )).scalars().all()

    for item in order.orders:
        for rule in rules:
            if rule.rule_type == "sku_prefix" and item.outer_sku_id:
                if item.outer_sku_id.startswith(rule.rule_value):
                    return True
            elif rule.rule_type == "category_id" and item.cid:
                if item.cid == rule.rule_value:
                    return True
            elif rule.rule_type == "seller_code" and item.outer_sku_id:
                if rule.rule_value in item.outer_sku_id:
                    return True
    return False


async def process_order(
    tid: str,
    token: str,
    db: AsyncSession,
    agiso: AgisoClient,
    jdy: JiandaoyunClient,
) -> None:
    """处理单个订单的完整发货流程"""

    # 查或创建发货记录
    record = (await db.execute(
        select(ShipmentRecord).where(ShipmentRecord.taobao_order_id == tid)
    )).scalar_one_or_none()

    if record is None:
        record = ShipmentRecord(
            taobao_order_id=tid,
            status=ShipmentStatus.pending,
            merchant_token=token or None,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
    elif token and not record.merchant_token:
        # 补偿任务重试时可能没有 token，优先用 Webhook 推送时保存的
        record.merchant_token = token
        await db.commit()

    # 取持久化的 token（补偿重试时 job 里 token 为空时用）
    effective_token = record.merchant_token or token

    if record.status == ShipmentStatus.shipped:
        logger.info("Order %s already shipped, skip", tid)
        return

    if record.retry_count >= MAX_RETRY:
        if record.status != ShipmentStatus.failed:
            record.status = ShipmentStatus.failed
            await db.commit()
            await alert_ship_failed(tid, record.error_message or "超过最大重试次数")
        return

    # 标记处理中
    record.status = ShipmentStatus.processing
    await db.commit()

    try:
        # 1. 拉取订单详情，获取商品 SKU 列表
        detail_resp = await agiso.get_order_detail(effective_token, tid)
        order_items = _parse_order_items(detail_resp)
        order = AgisoOrder(tid=tid, orders=order_items, raw=detail_resp)

        # 2. 判断是否副卡商品
        if not await is_fuka_order(order, db):
            logger.info("Order %s is not a fuka order, skip", tid)
            record.status = ShipmentStatus.shipped  # 非副卡订单不需要处理，标记完成跳过
            record.error_message = "非副卡商品，跳过"
            await db.commit()
            return

        # 记录 SKU（取第一个匹配的商品）
        if order_items:
            record.product_sku = order_items[0].outer_sku_id or order_items[0].sku_id
            await db.commit()

        # 3. 获取可用副卡
        fuka = await jdy.get_available_fuka()
        if fuka is None:
            record.status = ShipmentStatus.pending_manual
            record.error_message = "无可用副卡"
            await db.commit()
            await alert_no_fuka(tid)
            return

        # 4. 调阿奇索发货
        delivery_msg = f"您好，您购买的副卡链接如下，请查收：\n{fuka.link}"
        ship_result = await agiso.ship_order(effective_token, tid, delivery_msg)

        if ship_result.get("code") not in (None, 0, "0", "success", 200):
            raise RuntimeError(f"阿奇索发货失败: {ship_result}")

        # 5. 更新简道云状态（失败由补偿任务重试）
        try:
            await jdy.mark_fuka_used(fuka.record_id, tid)
        except Exception as e:
            logger.error("JDY update failed for order %s, will retry: %s", tid, e)

        # 6. 更新本地发货记录
        record.status = ShipmentStatus.shipped
        record.jdy_record_id = fuka.record_id
        record.jdy_content = fuka.raw
        record.error_message = None
        await db.commit()
        logger.info("Order %s shipped via fuka %s", tid, fuka.record_id)

    except Exception as e:
        record.retry_count += 1
        record.status = ShipmentStatus.pending
        record.error_message = str(e)
        await db.commit()
        logger.exception("Error processing order %s (retry %d): %s", tid, record.retry_count, e)

        if record.retry_count >= MAX_RETRY:
            record.status = ShipmentStatus.failed
            await db.commit()
            await alert_ship_failed(tid, str(e))
