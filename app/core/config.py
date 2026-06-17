from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 阿奇索
    agiso_app_id: str
    agiso_app_secret: str
    agiso_base_url: str = "https://gw-api.agiso.com"

    # 简道云
    jdy_api_key: str
    jdy_app_id: str
    jdy_entry_id: str
    jdy_field_status: str = "_widget_1686470745010"
    jdy_field_expire: str = "_widget_1686468122287"
    jdy_field_link: str = "_widget_1742477595612"
    jdy_field_order_id: str = "_widget_1686468122289"
    jdy_status_available: str = "副卡未售"
    jdy_status_used: str = "副卡已售"

    # MySQL
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_user: str = "fuka"
    mysql_password: str
    mysql_db: str = "fukazidongfa"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # 邮件告警
    alert_email_to: str
    smtp_host: str = "smtp.163.com"
    smtp_port: int = 465
    smtp_user: str
    smtp_password: str

    # 服务
    log_level: str = "INFO"
    webhook_secret: str = "change_this"
    worker_concurrency: int = 4
    scheduler_interval_minutes: int = 10

    @property
    def db_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"
        )

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
