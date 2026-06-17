CREATE TABLE IF NOT EXISTS shipment_records (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    taobao_order_id VARCHAR(64)  NOT NULL,
    jdy_record_id   VARCHAR(64)  DEFAULT NULL,
    product_sku     VARCHAR(128) DEFAULT NULL,
    jdy_content     JSON         DEFAULT NULL,
    status          ENUM('pending','processing','shipped','failed','pending_manual')
                    NOT NULL DEFAULT 'pending',
    merchant_token  VARCHAR(256) DEFAULT NULL,
    retry_count     TINYINT      NOT NULL DEFAULT 0,
    error_message   TEXT         DEFAULT NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_order (taobao_order_id),
    INDEX idx_status (status),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS fuka_product_rules (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    rule_type   ENUM('sku_prefix','category_id','seller_code') NOT NULL,
    rule_value  VARCHAR(128) NOT NULL,
    enabled     TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 示例副卡商品规则（按实际 SKU 前缀/类目修改）
INSERT INTO fuka_product_rules (rule_type, rule_value, enabled) VALUES
('sku_prefix', 'fuka_', 1),
('seller_code', 'FUKA', 1);
