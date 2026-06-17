from datetime import datetime
from sqlalchemy import BigInteger, String, JSON, Text, SmallInteger, Enum, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import enum


class ShipmentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    shipped = "shipped"
    failed = "failed"
    pending_manual = "pending_manual"


class ShipmentRecord(Base):
    __tablename__ = "shipment_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    taobao_order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    jdy_record_id: Mapped[str | None] = mapped_column(String(64))
    product_sku: Mapped[str | None] = mapped_column(String(128))
    jdy_content: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(ShipmentStatus), nullable=False, default=ShipmentStatus.pending, index=True
    )
    merchant_token: Mapped[str | None] = mapped_column(String(256))
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class FukaProductRule(Base):
    __tablename__ = "fuka_product_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_type: Mapped[str] = mapped_column(
        Enum("sku_prefix", "category_id", "seller_code"), nullable=False
    )
    rule_value: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
