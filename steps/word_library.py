# steps/word_library.py
# AI 生成此文件时，只需要关注：
# 1. 步骤执行顺序
# 2. 每个步骤的 strategies（从 cleaned JSON 中读取）
# 3. 步骤间的 URL 跳转

from core.selector import smart_click, smart_fill, robust_locate
from core.browser import BrowserManager

class WordLibrarySteps:
    def __init__(self, browser: BrowserManager):
        self.browser = browser

    async def execute(self):
        await self.step_enter_ads()
        await self.step_open_word_stock()
        await self.step_create_library()
        # ...

    async def step_enter_ads(self):
        # 直接写策略（AI 从 cleaned JSON 生成）
        strategies = [
            {"type": "text", "value": "广告"},
        ]
        page = self.browser.page
        await smart_click(page, strategies)
        await self.browser.wait(3)

    async def step_open_word_stock(self):
        self.browser.page = await self.browser.new_page()
        await self.browser.page.goto("https://ads.lingxing.com/amazon/word-stock")
        await self.browser.wait(3)

    async def step_create_library(self):
        page = self.browser.page
        # 点击"新建词库"
        strategies = [
            {"type": "text", "value": "新建词库"},
        ]
        await smart_click(page, strategies)
        await self.browser.wait(2)

        # 填写词库名称（锚定策略优先）
        strategies = [
            {"type": "anchored", "anchor": {"type": "role", "value": "dialog"}, "target": {"type": "placeholder", "value": "请输入"}},
            {"type": "placeholder", "value": "请输入"},
        ]
        await smart_fill(page, strategies, "B09WMHTQFX123121阿达3")
        await self.browser.wait(0.5)