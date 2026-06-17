import logging
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def send_alert(subject: str, body: str) -> None:
    msg = MIMEMultipart()
    msg["From"] = settings.smtp_user
    msg["To"] = settings.alert_email_to
    msg["Subject"] = f"[副卡发货告警] {subject}"
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=True,
        )
        logger.info("Alert email sent: %s", subject)
    except Exception as e:
        logger.error("Failed to send alert email: %s", e)


async def alert_no_fuka(order_id: str) -> None:
    await send_alert(
        subject=f"订单 {order_id} 无可用副卡",
        body=(
            f"淘宝订单 {order_id} 需要发货，但简道云中无满足条件的副卡（未售且24小时内到期）。\n"
            "请及时处理，手动发货或补充副卡库存。"
        ),
    )


async def alert_ship_failed(order_id: str, error: str) -> None:
    await send_alert(
        subject=f"订单 {order_id} 发货失败",
        body=f"淘宝订单 {order_id} 调用阿奇索发货接口失败，已重试3次。\n错误信息：{error}\n请人工处理。",
    )
