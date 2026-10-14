"""نقطهٔ ورود: ``python -m bot``"""
from __future__ import annotations

import asyncio
import logging
import sys

from .app import GameBot
from .bale_api import BaleAPI
from .config import Settings


async def _main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    api = BaleAPI(settings.token, settings.api_base, poll_timeout=settings.poll_timeout)
    bot = GameBot(api, settings)
    try:
        await bot.run()
    finally:
        await api.close()


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nربات متوقف شد.", file=sys.stderr)


if __name__ == "__main__":
    main()
