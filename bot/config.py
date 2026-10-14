"""تنظیمات ربات از متغیرهای محیطی (و فایل .env در صورت وجود)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _load_dotenv() -> None:
    """اگر python-dotenv نصب باشد فایل .env را می‌خواند؛ در غیر این صورت بی‌صدا رد می‌شود."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    load_dotenv()


@dataclass(frozen=True)
class Settings:
    token: str
    api_base: str = "https://tapi.bale.ai"
    poll_timeout: int = 30          # ثانیه؛ Long Polling در getUpdates
    turn_timeout: float = 120.0     # ثانیه؛ حداکثر زمان هر نوبت
    queue_timeout: float = 180.0    # ثانیه؛ حداکثر انتظار در صف
    cpu_delay: float = 0.7          # ثانیه؛ مکث «فکر کردن» کامپیوتر
    housekeeping_interval: float = 5.0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        token = os.getenv("BALE_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "BALE_TOKEN تنظیم نشده است. توکن را از @botfather در بله بگیرید و در فایل .env قرار دهید "
                "(نمونه: .env.example)."
            )
        return cls(
            token=token,
            api_base=os.getenv("BALE_API_BASE", cls.api_base).rstrip("/"),
            poll_timeout=int(os.getenv("POLL_TIMEOUT", cls.poll_timeout)),
            turn_timeout=float(os.getenv("TURN_TIMEOUT", cls.turn_timeout)),
            queue_timeout=float(os.getenv("QUEUE_TIMEOUT", cls.queue_timeout)),
            cpu_delay=float(os.getenv("CPU_DELAY", cls.cpu_delay)),
            housekeeping_interval=float(os.getenv("HOUSEKEEPING_INTERVAL", cls.housekeeping_interval)),
            log_level=os.getenv("LOG_LEVEL", cls.log_level).upper(),
        )
