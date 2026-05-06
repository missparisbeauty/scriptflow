"""APScheduler 排程 — Phase 5。

每日 09:00（GMT+8）觸發 CrawlerService.run_daily_crawl()
分別跑三個分類：美妝 / 美食 / 髮品。

設計：
  - 由 main.py 在啟動 lifespan 啟動排程
  - 排程設定可被環境變數 SCHEDULER_ENABLED=false 關閉（測試）
  - 失敗只 log，不中斷其他分類
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from modules.crawler.service import run_daily_crawl

logger = logging.getLogger(__name__)

DAILY_HOUR = 9
DAILY_MINUTE = 0
TIMEZONE = "Asia/Taipei"  # GMT+8
CATEGORIES = ("美妝", "美食", "髮品")

_scheduler: BackgroundScheduler | None = None


def is_enabled() -> bool:
    val = os.getenv("SCHEDULER_ENABLED", "true").strip().lower()
    return val in {"1", "true", "yes", "on"}


def daily_crawl_job() -> None:
    """同時跑三個分類；單一失敗不中斷其他。"""
    for category in CATEGORIES:
        try:
            res = run_daily_crawl(category)
            logger.info(
                "scheduler.crawl ok category=%s candidate_id=%s",
                category,
                res.get("candidate_id"),
            )
        except Exception as e:
            logger.error(
                "scheduler.crawl failed category=%s err=%s",
                category,
                type(e).__name__,
            )


def start() -> BackgroundScheduler | None:
    """啟動排程；已啟動會重用同一個。"""
    global _scheduler
    if not is_enabled():
        logger.info("scheduler disabled by env")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone=TIMEZONE)
    _scheduler.add_job(
        daily_crawl_job,
        trigger="cron",
        hour=DAILY_HOUR,
        minute=DAILY_MINUTE,
        id="daily_crawl",
        replace_existing=True,
    )
    _scheduler.start()
    next_run = _scheduler.get_job("daily_crawl").next_run_time
    logger.info("scheduler started; next daily_crawl=%s", next_run)
    return _scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler stopped")


def get_status() -> dict:
    """供前端顯示排程狀態。"""
    if _scheduler is None:
        return {"enabled": is_enabled(), "running": False, "next_run": None}
    job = _scheduler.get_job("daily_crawl")
    next_run = job.next_run_time if job else None
    return {
        "enabled": True,
        "running": _scheduler.running,
        "next_run": next_run.isoformat() if next_run else None,
        "timezone": TIMEZONE,
    }
