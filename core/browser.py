"""浏览器管理器 - 稳定不变"""

import asyncio
import os
from typing import Optional
from dataclasses import dataclass
from playwright.async_api import async_playwright, Page, BrowserContext


@dataclass
class BrowserConfig:
    headless: bool = False
    user_data_dir: str = "playwright_profile"
    channel: str = "chrome"
    locale: str = "zh-CN"
    timeout: int = 30000


class BrowserManager:
    def __init__(self, config: BrowserConfig = None):
        self.config = config or BrowserConfig()
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def launch(self) -> Page:
        self.playwright = await async_playwright().start()
        os.makedirs(self.config.user_data_dir, exist_ok=True)

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.config.user_data_dir,
            channel=self.config.channel,
            headless=self.config.headless,
            no_viewport=True,
            locale=self.config.locale,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.config.timeout)
        return self.page

    async def new_page(self) -> Page:
        pg = await self.context.new_page()
        pg.set_default_timeout(self.config.timeout)
        return pg

    async def wait(self, seconds: float = 1.0):
        await asyncio.sleep(seconds)

    async def screenshot(self, name: str):
        os.makedirs("debug_screenshots", exist_ok=True)
        path = f"debug_screenshots/{name}.png"
        await self.page.screenshot(path=path, full_page=True)

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()