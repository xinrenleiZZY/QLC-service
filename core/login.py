"""登录管理器 - 稳定不变"""

from .browser import BrowserManager


class LoginConfig:
    url: str = "https://huizhixin.lingxing.com/erp/home"
    account: str = ""
    password: str = ""
    login_btn_xpath: str = '/html/body/div[2]/div/div[1]/div/div[2]/div[2]/div/div[1]'


class LoginManager:
    def __init__(self, browser: BrowserManager, config: LoginConfig):
        self.browser = browser
        self.config = config

    async def ensure_logged_in(self, max_retries: int = 3) -> bool:
        for attempt in range(1, max_retries + 1):
            await self.browser.page.goto(self.config.url)
            await self.browser.wait(2)

            login_btn = self.browser.page.locator(f'xpath={self.config.login_btn_xpath}')
            if await login_btn.count() > 0 and await login_btn.is_visible():
                print(f"  [登录] 检测到登录按钮 (第{attempt}次)")
                await self._do_login()
                return True

            if attempt < max_retries:
                print(f"  [登录] 重试...")
                await self.browser.wait(1)

        print("  [登录] 已登录，跳过")
        return True

    async def _do_login(self):
        # 点击"账号登录"
        await self._click_text("账号登录")
        await self.browser.wait(1)

        # 输入账号
        await self._fill_by_placeholder("请输入账号", self.config.account)
        await self.browser.wait(0.5)

        # 输入密码
        await self._fill_by_placeholder("请输入密码", self.config.password)
        await self.browser.wait(0.5)

        # 勾选保存密码
        await self._click_xpath('/html/body/div[2]/div/div[1]/div/div[2]/div[2]/form/div[3]/label')
        await self.browser.wait(0.5)

        # 点击登录
        await self._click_text("登录")

        # 等待登录完成
        for _ in range(15):
            current = self.browser.page.url
            if "/erp/home" in current or "login" not in current.lower():
                break
            await self.browser.wait(2)

    async def _click_text(self, text: str):
        btn = self.browser.page.get_by_text(text, exact=True)
        if await btn.count() > 0:
            await btn.first.click()

    async def _fill_by_placeholder(self, placeholder: str, value: str):
        inp = self.browser.page.get_by_placeholder(placeholder)
        if await inp.count() > 0:
            await inp.first.fill(value)

    async def _click_xpath(self, xpath: str):
        await self.browser.page.click(f'xpath={xpath}')