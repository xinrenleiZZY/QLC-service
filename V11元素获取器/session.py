"""
session.py - 浏览器长连接会话（独立基础设施）
=============================================

职责:
  - 启动 Playwright 浏览器（唯一实例）
  - 管理 CDP 引擎（长连接）
  - 管理 OCR 引擎
  - 提供 page, context, cdp, ocr 给所有模块使用
  - 不关闭，直到显式调用 close()

用法:
    session = await BrowserSession.create()
    page = session.page
    # ... 多个模块共享同一个 page
    await session.close()
"""

import asyncio
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from playwright.async_api import async_playwright


# ============================================================
#  导入 CDP 和 OCR 引擎（从 advanced_runner 复用）
# ============================================================
try:
    from advanced_runner import CDPEngine, OCREngine, EventBus
except ImportError:
    # 兜底：如果没有 advanced_runner，用空实现
    class EventBus:
        async def emit(self, *a, **kw): pass
    class CDPEngine:
        def __init__(self, eb): self.connected = False
        async def connect(self, *a): pass
        async def disconnect(self): pass
        async def evaluate(self, *a): return {}
        async def deep_search_element(self, *a): return None
        async def capture_state(self): return {}
    class OCREngine:
        def __init__(self, page, eb): self.available = False
        async def find_text_from_strategies(self, *a): return {"found": False}


class BrowserSession:
    """
    浏览器长连接会话。
    - 单例设计（不应该创建多个实例）
    - 提供 page, context, cdp, ocr 等核心对象
    - 跨多个模块共享
    """

    _instance = None

    @classmethod
    async def create(cls, user_data_dir="playwright_profile",
                     channel="chrome", headless=False,
                     no_viewport=True, locale="zh-CN") -> "BrowserSession":
        """创建（或复用）浏览器会话"""
        # 优先复用已有实例
        if cls._instance is not None and cls._instance._alive:
            print("  📌 复用已有浏览器会话")
            return cls._instance

        # 检测端口 18800 上是否有正在运行的浏览器
        existing = await cls._detect_existing(port=18800)
        if existing:
            print("  📌 检测到端口 18800 已有浏览器，连接复用")
            return existing

        instance = cls()
        instance._alive = False
        instance.user_data_dir = user_data_dir
        instance.channel = channel
        instance.headless = headless
        instance.no_viewport = no_viewport
        instance.locale = locale

        instance._pw = None
        instance._context = None
        instance.page = None
        instance.cdp = None
        instance.ocr = None
        instance.event_bus = EventBus()

        await instance._start()
        cls._instance = instance
        return instance

    @classmethod
    async def _detect_existing(cls, port=18800):
        """检测端口上是否有运行中的浏览器实例"""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result != 0:
                return None

            # 尝试连接 CDP
            from playwright.async_api import async_playwright as _ap
            p = await _ap().start()
            try:
                browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                instance = cls.__new__(cls)
                instance._pw = p
                instance._browser = browser
                instance._context = browser.contexts[0] if browser.contexts else None
                instance.page = instance._context.pages[0] if instance._context and instance._context.pages else None
                instance.cdp = CDPEngine(EventBus())
                if instance.page:
                    await instance.cdp.connect(instance.page)
                instance.ocr = OCREngine(instance.page, EventBus())
                instance.event_bus = EventBus()
                instance._alive = True
                instance._connected_via_cdp = True
                cls._instance = instance
                return instance
            except Exception:
                await p.stop()
                return None
        except Exception:
            return None

    async def _start(self):
        """启动浏览器"""
        # 清理残留
        self._cleanup_chrome()

        self._pw = await async_playwright().start()
        self._context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            channel=self.channel,
            headless=self.headless,
            no_viewport=self.no_viewport,
            locale=self.locale,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--remote-debugging-port=18800",
            ],
        )
        self.page = await self._context.new_page()
        self.page.set_default_timeout(30000)

        # 初始化引擎
        self.cdp = CDPEngine(self.event_bus)
        await self.cdp.connect(self.page)
        self.ocr = OCREngine(self.page, self.event_bus)

        self._alive = True
        print(f"  ✅ 浏览器已启动 | CDP: {'在线' if self.cdp.connected else '离线'}"
              f" | OCR: {'就绪' if self.ocr.available else '不可用'}")
        print(f"  🔌 CDP 调试地址: http://127.0.0.1:18800")
        print(f"     可用 debug_elements-V10.py --cdp http://127.0.0.1:18800 连接")

    def _cleanup_chrome(self):
        """清理残留 Chrome 进程"""
        import subprocess
        try:
            subprocess.run('taskkill /f /im chrome.exe 2>nul',
                           shell=True, capture_output=True, text=True)
        except Exception:
            pass

    async def navigate(self, url: str):
        """导航到 URL"""
        resolved = self._resolve_vars(url)
        print(f"  → 导航到: {resolved}")
        await self.page.goto(resolved, wait_until="load", timeout=20000)
        await asyncio.sleep(2)

    def _resolve_vars(self, text: str) -> str:
        """简单的变量解析"""
        import re
        # 尝试加载 vars.yaml
        vars_path = os.path.join(PROJECT_ROOT, "vars.yaml")
        vars_dict = {}
        if os.path.isfile(vars_path):
            try:
                import yaml
                with open(vars_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                vars_dict = {k: v for k, v in data.items() if isinstance(k, str)}
            except Exception:
                pass

        def _replacer(m):
            return str(vars_dict.get(m.group(1), m.group(0)))
        return re.sub(r'\$\{(\w+)\}', _replacer, text)

    async def close(self):
        """关闭浏览器会话"""
        if not self._alive:
            return
        await self.cdp.disconnect()

        # 如果是 CDP 连接的（外部浏览器），只断开不关闭
        if getattr(self, '_connected_via_cdp', False):
            self._alive = False
            self.page = None
            self._context = None
            if self._pw:
                await self._pw.stop()
            self._pw = None
            BrowserSession._instance = None
            print("  🚪 已断开与外部浏览器的 CDP 连接")
            return

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw:
            await self._pw.stop()
        self._alive = False
        self.page = None
        self._context = None
        self._pw = None
        BrowserSession._instance = None
        print("  🚪 浏览器会话已关闭")

    @property
    def alive(self) -> bool:
        return self._alive
