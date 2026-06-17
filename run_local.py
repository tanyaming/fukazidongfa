#!/usr/bin/env python3
"""
本地调试脚本：不依赖 Docker，直接连接本地 MySQL/Redis 运行服务。
用法：
  1. 确保本地 MySQL 和 Redis 已启动
  2. 修改 .env 中 MYSQL_HOST=localhost, REDIS_URL=redis://localhost:6379/0
  3. pip install -r requirements.txt
  4. python run_local.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="debug",
    )
