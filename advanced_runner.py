"""
advanced_runner.py - 下一代流程执行引擎
========================================

核心架构:
  ┌─────────────────────────────────────────────────────┐
  │                状态机 (StateMachine)                  │
  │  ┌─────────┐  found  ┌──────────┐                   │
  │  │ FINDING │───────→│ EXECUTING │                   │
  │  └────┬────┘        └─────┬────┘                   │
  │  not_found│               │ done                    │
  │       ┌──┴──┐             │                         │
  │       ▼     ▼              ▼                         │
  │  ┌─────────┐  retry ┌──────────┐                    │
  │  │ WAITING │───────→│ RETRYING │                    │
  │  └────┬────┘        └────┬─────┘                    │
  │   timeout│               │ max_retries              │
  │       ▼                  ▼                           │
  │  ┌───────────┐     ┌──────────┐                     │
  │  │ HUMAN_HELP│     │ SKIP/FAIL│                     │
  │  └─────┬─────┘     └──────────┘                     │
  │    user_ok│                                          │
  │         └──────────────────────────────────────────┘ │
  │                                                      │
  │  双引擎: Playwright(主) + CDP/Pyppeteer(辅)          │
  │  长连接: CDP Session 持续在线，实时DOM/网络调试        │
  └──────────────────────────────────────────────────────┘

用法:
    python advanced_runner.py <cleaned.json> [actions.yaml]
"""

import asyncio
import json
import os
import re
import sys
import time
import inspect
from pathlib import Path
from enum import Enum
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

try:
    import yaml as _yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from playwright.async_api import async_playwright
from core.selector import robust_locate

# 尝试导入 pyppeteer（可选）
try:
    import pyppeteer
    HAS_PYPPETEER = True
except ImportError:
    HAS_PYPPETEER = False


###############################################################################
#  状态机定义
###############################################################################

class StepState(Enum):
    """元素执行状态"""
    PENDING     = "pending"       # 等待执行
    FINDING     = "finding"       # 正在定位元素
    EXECUTING   = "executing"     # 正在执行操作
    WAITING     = "waiting"       # 等待条件满足
    RETRYING    = "retrying"      # 重试中
    HUMAN_HELP  = "human_help"    # 等待人工介入
    SUCCESS     = "success"       # 执行成功
    SKIP        = "skip"          # 已跳过
    FAIL        = "fail"          # 失败
    TIMEOUT     = "timeout"       # 超时


class FlowState(Enum):
    """整体流程状态"""
    INIT       = "init"
    RUNNING    = "running"
    PAUSED     = "paused"        # 等待人工介入时暂停
    COMPLETED  = "completed"
    ABORTED    = "aborted"


###############################################################################
#  事件系统
###############################################################################

class EventBus:
    """发布-订阅事件总线"""

    def __init__(self):
        self._handlers = {}

    def on(self, event: str, handler: Callable = None):
        """注册事件监听，支持装饰器语法 @bus.on('event') 和 直接调用 bus.on('event', fn)"""
        def decorator(fn):
            if event not in self._handlers:
                self._handlers[event] = []
            self._handlers[event].append(fn)
            return fn

        if handler is not None:
            # 直接调用: bus.on('event', handler)
            return decorator(handler)
        # 装饰器: @bus.on('event')
        return decorator

    def off(self, event: str, handler: Callable):
        if event in self._handlers:
            self._handlers[event] = [h for h in self._handlers[event] if h != handler]

    async def emit(self, event: str, **data):
        handlers = self._handlers.get(event, [])
        for h in handlers:
            if inspect.iscoroutinefunction(h):
                await h(event=event, **data)
            else:
                h(event=event, **data)

    def emit_sync(self, event: str, **data):
        """同步触发（用于非 async 场景）"""
        for h in self._handlers.get(event, []):
            if not inspect.iscoroutinefunction(h):
                h(event=event, **data)


###############################################################################
#  配置模型
###############################################################################

@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 5
    base_delay: float = 1.0        # 首次重试等待
    max_delay: float = 30.0        # 最大等待
    backoff_factor: float = 2.0    # 指数退避
    jitter: bool = True            # 随机抖动
    on_exhausted: str = "skip"     # retries / skip / fail / human

    def next_delay(self, attempt: int) -> float:
        import random
        delay = min(self.base_delay * (self.backoff_factor ** (attempt - 1)), self.max_delay)
        if self.jitter:
            delay *= 0.5 + random.random() * 0.5  # 50%-100% 随机
        return delay


@dataclass
class HumanInterventionConfig:
    """人工介入配置"""
    enabled: bool = True
    timeout: int = 300             # 等待人工操作的最大秒数
    prompt_on_failure: bool = True
    allow_skip: bool = True
    allow_retry: bool = True


@dataclass
class CDPConfig:
    """CDP 调试配置"""
    enabled: bool = True
    auto_debug_on_failure: bool = True   # 失败时自动进入 CDP 检查
    capture_screenshot: bool = True      # 截屏
    capture_html: bool = True            # 捕获 DOM 快照


@dataclass
class StepAction:
    """单个元素动作的全部信息"""
    index: int
    step_name: str
    strategies: list
    action: dict
    config: dict = field(default_factory=dict)  # 包含 retry, human, cdp 等


###############################################################################
#  CDP 引擎（Playwright CDP Session + Pyppeteer 双通道）
###############################################################################

class CDPEngine:
    """
    CDP 调试引擎。
    - 主通道: Playwright 的 new_cdp_session（轻量）
    - 辅通道: Pyppeteer（高级 CDP 操作）
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.pw_session = None   # Playwright CDP Session
        self.pup_page = None     # Pyppeteer Page
        self.pup_browser = None  # Pyppeteer Browser
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, page, browser=None):
        """连接 CDP，初始化双通道"""
        try:
            # 主通道: Playwright CDP Session
            if hasattr(page.context, 'new_cdp_session'):
                contexts = page.context
                if contexts and hasattr(contexts, 'browser'):
                    self.pw_session = await contexts.new_cdp_session(page)
                    self._connected = True
                    await self.event_bus.emit("cdp.connected", source="playwright")
        except Exception as e:
            await self.event_bus.emit("cdp.error", msg=f"PW CDP 连接失败: {e}")

        # 辅通道: Pyppeteer（可选）
        if HAS_PYPPETEER and browser:
            await self._connect_pyppeteer(browser)

    async def _connect_pyppeteer(self, pw_browser):
        """用 Pyppeteer 连接同一浏览器"""
        try:
            ws_endpoint = pw_browser.ws_endpoint if hasattr(pw_browser, 'ws_endpoint') else None
            if ws_endpoint:
                self.pup_browser = await pyppeteer.connect(
                    browserWSEndpoint=ws_endpoint,
                    slowMo=0
                )
                pages = await self.pup_browser.pages()
                if pages:
                    self.pup_page = pages[0]
                    self._connected = True
                    await self.event_bus.emit("cdp.connected", source="pyppeteer")
        except Exception as e:
            await self.event_bus.emit("cdp.warning", msg=f"Pyppeteer 连接失败: {e}")

    async def evaluate(self, js_code: str) -> dict:
        """执行 JS（优先 PW CDP，回退 pyppeteer）"""
        if self.pw_session:
            try:
                result = await self.pw_session.send("Runtime.evaluate", {
                    "expression": js_code,
                    "returnByValue": True,
                    "awaitPromise": True,
                })
                return result.get("result", {})
            except Exception:
                pass

        if self.pup_page:
            try:
                val = await self.pup_page.evaluate(js_code)
                return {"type": "object", "value": val}
            except Exception:
                pass

        return {"type": "string", "value": ""}

    async def deep_search_element(self, strategies: list) -> dict:
        """
        深度搜索元素（CDP 级 DOM 遍历）。
        穿透 Shadow DOM、iframe，用 JS 在页面任意位置查找。
        返回元素的 bounding rect 或 None。
        """
        # 从 strategies 中提取搜索条件
        css_selectors = [s["value"] for s in strategies if s.get("type") == "css" and s.get("value")]
        text_values = [s["value"] for s in strategies if s.get("type") == "text" and s.get("value")]

        if not css_selectors and not text_values:
            return None

        js = """
        (() => {
            const cssSelectors = """ + json.dumps(css_selectors) + """;
            const textValues = """ + json.dumps(text_values) + """;

            // 深度遍历 + Shadow DOM 穿透
            function deepQuery(root, selector) {
                // 1. 在当前根查
                let el = root.querySelector(selector);
                if (el) return el;

                // 2. 遍历所有元素，穿透 Shadow DOM
                const all = root.querySelectorAll('*');
                for (const node of all) {
                    if (node.shadowRoot) {
                        el = deepQuery(node.shadowRoot, selector);
                        if (el) return el;
                    }
                }

                // 3. 遍历 iframe（同域）
                const iframes = root.querySelectorAll('iframe');
                for (const iframe of iframes) {
                    try {
                        if (iframe.contentDocument) {
                            el = deepQuery(iframe.contentDocument, selector);
                            if (el) return el;
                        }
                    } catch(e) {}
                }
                return null;
            }

            // 按 CSS 选择器找
            for (const css of cssSelectors) {
                const el = deepQuery(document, css);
                if (el) {
                    const rect = el.getBoundingClientRect();
                    return {
                        found: true,
                        selector: css,
                        tag: el.tagName,
                        text: (el.textContent || '').trim().substring(0, 100),
                        x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                    };
                }
            }

            // 按文本找（更宽松）
            for (const txt of textValues) {
                const walker = document.createTreeWalker(document.body, 4, null, false);
                while (walker.nextNode()) {
                    const node = walker.currentNode;
                    if (node.nodeType === 1) {
                        const text = (node.textContent || '').trim();
                        if (text === txt || text.includes(txt)) {
                            const rect = node.getBoundingClientRect();
                            return {
                                found: true,
                                selector: 'text:' + txt,
                                tag: node.tagName,
                                text: text.substring(0, 100),
                                x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                            };
                        }
                    }
                }
            }

            return { found: false };
        })()
        """

        result = await self.evaluate(js)
        if isinstance(result, dict):
            val = result.get("value")
            if isinstance(val, dict) and val.get("found"):
                return val
        return None

    async def capture_state(self) -> dict:
        """捕获当前页面状态快照"""
        state = {}
        try:
            state["title"] = (await self.evaluate("document.title")).get("value", "")
            state["url"] = (await self.evaluate("window.location.href")).get("value", "")
            state["dom_size"] = (await self.evaluate("document.querySelectorAll('*').length")).get("value", 0)
            state["viewport"] = await self.evaluate("JSON.stringify({w: window.innerWidth, h: window.innerHeight})")
        except Exception:
            pass
        return state

    async def disconnect(self):
        if self.pup_browser:
            try:
                await self.pup_browser.disconnect()
            except Exception:
                pass
        self.pw_session = None
        self._connected = False


###############################################################################
#  OCR 引擎（截图 + 文字识别兜底）
###############################################################################

try:
    import pytesseract as _pytesseract
    from PIL import Image, ImageDraw
    import io
    HAS_PYTESSERACT = True
    # 设置 tesseract 路径
    _tesseract_candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for _p in _tesseract_candidates:
        if os.path.isfile(_p):
            _pytesseract.pytesseract.tesseract_cmd = _p
            break
except ImportError:
    HAS_PYTESSERACT = False


class OCREngine:
    """
    OCR 图像识别引擎。
    截取页面截图 → OCR 识别文本 → 按文本找坐标 → 返回点击位置。
    作为 CDP 深度搜索失败后的最后一层兜底。
    """

    def __init__(self, page, event_bus: EventBus):
        self.page = page
        self.event_bus = event_bus

    @property
    def available(self) -> bool:
        return HAS_PYTESSERACT

    async def find_text(self, target_text: str) -> dict:
        """
        在页面截图中查找指定文本。
        返回: { found: bool, x: number, y: number, text: str, confidence: number }
        """
        if not self.available or not target_text:
            return {"found": False}

        try:
            # OCR 放入线程池执行，避免阻塞事件循环
            loop = asyncio.get_running_loop()

            def _ocr_one_image(img):
                return _pytesseract.image_to_data(
                    img, lang="chi_sim+eng",
                    output_type=_pytesseract.Output.DICT
                )

            # 截取当前页面截图
            screenshot_bytes = await self.page.screenshot(full_page=False)
            img = Image.open(io.BytesIO(screenshot_bytes))

            # 在 executor 中运行 OCR（同步阻塞操作）
            ocr_data = await loop.run_in_executor(None, _ocr_one_image, img)

            best_match = None
            best_score = 0

            for i in range(len(ocr_data["text"])):
                text = (ocr_data["text"][i] or "").strip()
                if not text:
                    continue

                conf = int(ocr_data["conf"][i]) if ocr_data["conf"][i] != "-1" else 0

                # 检查目标文本是否在识别的文本中
                if target_text in text or text in target_text:
                    score = conf * (len(text) / max(len(target_text), 1))
                    if score > best_score:
                        best_score = score
                        x = ocr_data["left"][i] + ocr_data["width"][i] // 2
                        y = ocr_data["top"][i] + ocr_data["height"][i] // 2
                        best_match = {
                            "found": True,
                            "x": x,
                            "y": y,
                            "text": text,
                            "confidence": conf,
                            "width": ocr_data["width"][i],
                            "height": ocr_data["height"][i],
                        }

            if best_match:
                await self.event_bus.emit("ocr.found",
                                          text=best_match["text"],
                                          x=best_match["x"],
                                          y=best_match["y"])
                return best_match

            # 没找到 → 再试全页截图（可能是滚动区域）
            screenshot_bytes_full = await self.page.screenshot(full_page=True)
            img_full = Image.open(io.BytesIO(screenshot_bytes_full))
            ocr_data_full = await loop.run_in_executor(None, _ocr_one_image, img_full)

            for i in range(len(ocr_data_full["text"])):
                text = (ocr_data_full["text"][i] or "").strip()
                if not text:
                    continue
                if target_text in text or text in target_text:
                    conf = int(ocr_data_full["conf"][i]) if ocr_data_full["conf"][i] != "-1" else 0
                    return {
                        "found": True,
                        "x": ocr_data_full["left"][i] + ocr_data_full["width"][i] // 2,
                        "y": ocr_data_full["top"][i] + ocr_data_full["height"][i] // 2,
                        "text": text,
                        "confidence": conf,
                    }

            return {"found": False}

        except Exception as e:
            await self.event_bus.emit("ocr.error", msg=str(e))
            return {"found": False}

    async def find_text_from_strategies(self, strategies: list) -> dict:
        """
        从 strategies 中提取所有可能的文本关键词，用 OCR 搜素。
        支持 anchored / text / placeholder / description 等所有策略类型。
        """
        search_terms = set()

        for s in strategies:
            stype = s.get("type", "")

            # 1. 直接文本匹配
            if stype == "text" and s.get("value"):
                search_terms.add(s["value"].strip())

            # 2. placeholder
            elif stype == "placeholder" and s.get("value"):
                search_terms.add(s["value"].strip())

            # 3. anchored → target value
            elif stype == "anchored":
                target = s.get("target", {})
                if target.get("value"):
                    search_terms.add(target["value"].strip())
                # anchored 的 description 里经常有 "id=app 内 text=账号登录"
                desc = s.get("description", "")
                if desc and "text=" in desc:
                    # 提取 text= 后面的内容
                    parts = desc.split("text=")
                    if len(parts) > 1:
                        search_terms.add(parts[-1].strip())

            # 4. description 字段（很多策略有描述信息）
            if s.get("description") and "text=" not in s.get("description", ""):
                desc = s["description"].strip()
                # 只取有意义的中文/英文描述（排除纯 CSS）
                if len(desc) > 2 and not desc.startswith(".") and not desc.startswith("#"):
                    search_terms.add(desc[:20])

            # 5. name 属性
            if stype == "name" and s.get("value"):
                search_terms.add(s["value"].strip())

        # 去重排序：短文本优先（OCR 对短文本准确率更高）
        search_terms = sorted(search_terms, key=len)

        if not search_terms:
            return {"found": False}

        # 打印 OCR 启动提示
        print(f"      👁️  OCR启动, 搜索: {list(search_terms)[:3]}...")

        for term in search_terms:
            short_term = term[:15]  # 取前15字符
            result = await self.find_text(short_term)
            if result.get("found"):
                return result

        return {"found": False}


###############################################################################
#  状态机执行器
###############################################################################

class StepRunner:
    """
    单步执行器，包含完整的状态转换 + 重试 + 人工介入。
    """

    def __init__(self, page, cdp: CDPEngine, event_bus: EventBus,
                 elements: list, vars_dict: dict, human_config: HumanInterventionConfig):
        self.page = page
        self.cdp = cdp
        self.ocr = OCREngine(page, event_bus)  # OCR 引擎（最后一层兜底）
        self.event_bus = event_bus
        self.elements = elements
        self.vars_dict = vars_dict
        self.human_config = human_config
        self.state = StepState.PENDING
        self.parent_locator = None
        self._active_zone = None  # 当前所在的区域名

    def reset_parent(self):
        """跨页面时重置父元素容器"""
        self.parent_locator = None

    def set_zone(self, zone_name: str):
        """标记当前区域"""
        self._active_zone = zone_name

    # ── 变量解析 ──
    def _resolve(self, text: str) -> str:
        def _replacer(m):
            return str(self.vars_dict.get(m.group(1), m.group(0)))
        return re.sub(r'\$\{(\w+)\}', _replacer, text)

    # ── 定位（CDP 增强） ──
    async def _locate(self, strategies: list, max_retries=5, retry_delay=1.0,
                      action_type="click"):
        """
        定位元素 - PW 主 + CDP 辅 + OCR 图像识别兜底。
        返回:
          - Playwright Locator → 成功找到
          - ("cdp_found", rect) → CDP/OCR 找到，坐标信息
          - None → 找不到
        """
        for attempt in range(1, max_retries + 1):
            # 1. 先用 Playwright 定位
            loc = await robust_locate(self.page, strategies,
                                      parent_locator=self.parent_locator)
            if loc is not None:
                try:
                    if await loc.is_visible():
                        return loc
                except Exception:
                    return loc

            # 2. PW 失败 → CDP 深度搜索（只找不点）
            if self.cdp.connected:
                deep = await self.cdp.deep_search_element(strategies)
                if deep and deep.get("found"):
                    return ("cdp_found", deep)

            if attempt < max_retries:
                await asyncio.sleep(retry_delay)

        # ── 3. 所有重试用完 → OCR 图像识别兜底 ──
        if self.ocr.available:
            print(f"      👁️  启动OCR图像识别（5-10秒）...")
            ocr_result = await self.ocr.find_text_from_strategies(strategies)
            if ocr_result.get("found"):
                await self.event_bus.emit("ocr.found",
                                          text=ocr_result.get("text", ""),
                                          x=ocr_result["x"], y=ocr_result["y"])
                return ("ocr_found", ocr_result)

        return None

    # ── 执行动作 ──
    async def _execute_action(self, loc, action: dict):
        """对已定位的元素执行操作"""
        action_type = action.get("type", "click")

        # ── locate_parent 优先处理 ──
        if action_type == "locate_parent":
            if isinstance(loc, tuple) and loc[0] in ("cdp_found", "ocr_found"):
                deep = loc[1]
                x = deep["x"]
                y = deep["y"]
                await self.page.mouse.click(x, y)
                return ("parent", None)
            else:
                return ("parent", loc)

        # CDP/OCR 找到的（非 locate_parent）
        if isinstance(loc, tuple):
            if loc[0] == "cdp_found":
                deep = loc[1]
                x = deep["x"] + deep["width"] // 2
                y = deep["y"] + deep["height"] // 2
                await self.page.mouse.click(x, y)
                return True, "CDP深度搜索→已点击"
            if loc[0] == "ocr_found":
                deep = loc[1]
                x = deep["x"]
                y = deep["y"]
                await self.page.mouse.click(x, y)
                ocr_text = deep.get("text", "")[:30]
                return True, f"OCR图像识别→已点击({ocr_text})"

        # 操作前等待
        wait_before = action.get("wait_before", 0.3)
        if wait_before > 0:
            await asyncio.sleep(wait_before)

        try:
            if action_type == "click":
                await loc.click()
            elif action_type == "fill":
                raw = action.get("value", "")
                val = self._resolve(raw)
                if action.get("clear_first", True):
                    await loc.fill("")
                await loc.fill(val)
            elif action_type == "wait_visible":
                await loc.wait_for(state="visible", timeout=10000)
            elif action_type == "hover":
                await loc.hover()
            elif action_type == "select":
                raw = action.get("value", "")
                val = self._resolve(raw)
                await loc.select_option(val)
            elif action_type == "scroll_to":
                await loc.scroll_into_view_if_needed()
            elif action_type == "screenshot":
                name = action.get("screenshot_name", f"step_{id(loc)}")
                os.makedirs("screenshots", exist_ok=True)
                await loc.screenshot(path=f"screenshots/{name}.png")
            elif action_type == "check_exists":
                return True, "元素存在"
            elif action_type == "check_visible":
                visible = await loc.is_visible()
                return True, f"元素{'可见' if visible else '不可见'}"
            elif action_type == "locate_parent":
                return ("parent", loc)
            else:
                await loc.click()
        except Exception as e:
            return False, str(e)

        # 操作后等待
        if action_type not in ("scroll_to", "screenshot", "check_exists", "check_visible"):
            ws = action.get("wait_strategy", "timeout")
            try:
                if ws == "navigation":
                    await self.page.wait_for_load_state("load", timeout=15000)
                elif ws == "element_appear":
                    await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            wa = action.get("wait_after", 0.5)
            if wa > 0:
                await asyncio.sleep(wa)

        return True, "成功"

    # ── 执行步骤（完整状态机） ──
    async def run(self, step: StepAction) -> tuple:
        """
        执行一个步骤，返回 (状态, 消息)
        包含完整的状态转换、重试、CDP 兜底、人工介入
        """
        self.state = StepState.FINDING
        await self.event_bus.emit("step.start", index=step.index, step_name=step.step_name)

        # 获取重试配置
        retry_cfg = RetryConfig(**{
            k: v for k, v in (step.config.get("retry", {})).items()
            if k in RetryConfig.__dataclass_fields__
        })

        # IF 条件检查
        if_config = step.action.get("if")
        if if_config and isinstance(if_config, dict):
            cond = if_config.get("condition")
            ref_idx = if_config.get("ref_index")
            if cond and ref_idx is not None:
                if 0 <= ref_idx < len(self.elements):
                    ref_item = self.elements[ref_idx]
                    ref_strategies = ref_item.get("cleaned", {}).get("strategies", [])
                    ref_loc = await robust_locate(self.page, ref_strategies,
                                                  parent_locator=self.parent_locator)
                    ref_exists = ref_loc is not None
                    should_execute = (cond == "element_exists" and ref_exists) or \
                                     (cond == "element_not_exists" and not ref_exists)
                    if not should_execute:
                        self.state = StepState.SKIP
                        skip_msg = f"IF条件不满足: {cond} ref=#{ref_idx}"
                        await self.event_bus.emit("step.skip", reason=skip_msg)
                        return (self.state, skip_msg)

        # ── 定位 + 重试循环 ──
        last_error = None
        loc = None
        cdp_deep_result = None

        for attempt in range(1, retry_cfg.max_retries + 1):
            self.state = StepState.FINDING if attempt == 1 else StepState.RETRYING
            await self.event_bus.emit("step.retry", attempt=attempt,
                                      max_retries=retry_cfg.max_retries)

            # 定位
            loc = await self._locate(step.strategies,
                                     action_type=step.action.get("type", "click"))

            if loc is not None:
                break  # 定位成功

            # CDP 深度搜索（如果还没试过）
            if self.cdp.connected and attempt >= 3:  # 第三次重试启用 CDP
                deep = await self.cdp.deep_search_element(step.strategies)
                if deep and deep.get("found"):
                    cdp_deep_result = deep
                    loc = ("cdp_clicked", deep)
                    break

            last_error = f"定位失败 (第{attempt}次)"

            if attempt < retry_cfg.max_retries:
                delay = retry_cfg.next_delay(attempt)
                self.state = StepState.WAITING
                await self.event_bus.emit("step.waiting", delay=delay,
                                          attempt=attempt)
                await asyncio.sleep(delay)

        # ── 结果处理 ──
        if loc is not None:
            self.state = StepState.EXECUTING

            # 高亮（如果是 PW Locator）
            if not isinstance(loc, tuple):
                try:
                    await loc.highlight()
                except Exception:
                    pass

            result, msg = await self._execute_action(loc, step.action)

            if isinstance(result, tuple) and result[0] == "parent":
                # 父元素容器
                self.parent_locator = result[1]
                self.state = StepState.SUCCESS
                if result[1] is not None:
                    parent_note = "（容器生效）"
                else:
                    parent_note = "（CDP定位，无容器）"
                await self.event_bus.emit("step.parent", index=step.index)
                return (self.state, f"父元素已捕获{parent_note}")

            if result is True:
                self.state = StepState.SUCCESS
                await self.event_bus.emit("step.success", index=step.index)
                return (self.state, msg)
            else:
                # 操作异常
                self.state = StepState.FAIL
                await self.event_bus.emit("step.fail", error=msg)
                return (self.state, f"操作失败: {msg}")

        # ── 所有重试用尽 ──
        # CDP 截图保存现场
        if self.cdp.connected:
            await self._capture_debug_info(step)

        exhausted_action = retry_cfg.on_exhausted  # skip / fail / human

        # 人工介入
        if exhausted_action == "human" and self.human_config.enabled:
            self.state = StepState.HUMAN_HELP
            await self.event_bus.emit("step.human_help",
                                      index=step.index,
                                      step_name=step.step_name)
            result = await self._wait_human_intervention(step)
            return result

        if exhausted_action == "skip":
            self.state = StepState.SKIP
            await self.event_bus.emit("step.skip", reason=last_error)
            return (self.state, f"已跳过: {last_error}")

        self.state = StepState.FAIL
        await self.event_bus.emit("step.fail", error=last_error)
        return (self.state, last_error)

    async def _capture_debug_info(self, step: StepAction):
        """捕获调试信息"""
        try:
            state = await self.cdp.capture_state()
            debug_dir = os.path.join(PROJECT_ROOT, "debug_captures")
            os.makedirs(debug_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(debug_dir, f"step_{step.index}_{ts}.json")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({
                    "step_index": step.index,
                    "step_name": step.step_name,
                    "page_state": state,
                    "strategies": step.strategies,
                    "action": step.action,
                }, f, ensure_ascii=False, indent=2)
            # 截屏
            if self.human_config.timeout > 0:
                try:
                    ss_path = os.path.join(debug_dir, f"step_{step.index}_{ts}.png")
                    await self.page.screenshot(path=ss_path, full_page=True)
                except Exception:
                    pass
        except Exception:
            pass

    async def _wait_human_intervention(self, step: StepAction) -> tuple:
        """
        等待人工介入。
        显示元素信息，等待用户选择：重试 / 跳过 / 终止
        """
        print(f"\n{'─'*60}")
        print(f"  ⚠️  元素定位失败，需要你确认")
        print(f"  步骤: {step.step_name}  (index={step.index})")
        print(f"  操作: {step.action.get('type', '?')}")
        print(f"  策略: {[s.get('type','?') for s in step.strategies[:3]]}")
        print(f"  CDP 深度搜索也已失败")
        print(f"\n  请选择:")
        print(f"    r — 手动处理后重试")
        print(f"    s — 跳过此元素")
        print(f"    f — 终止流程")
        print(f"  (等待 {self.human_config.timeout} 秒，超时则跳过)")
        print(f"{'─'*60}")

        start = time.time()
        while time.time() - start < self.human_config.timeout:
            remaining = int(self.human_config.timeout - (time.time() - start))
            try:
                # 使用 asyncio 方式等待输入
                loop = asyncio.get_running_loop()

                def _read():
                    import sys
                    import select
                    if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                        return sys.stdin.readline().strip().lower()
                    return None

                cmd = await loop.run_in_executor(None, _read)

                if cmd == 'r':
                    print("  → 用户选择重试")
                    # 递归重试一次（人工后直接 CDP）
                    loc = await self._locate(step.strategies, max_retries=3, retry_delay=2.0)
                    if loc:
                        result, msg = await self._execute_action(loc, step.action)
                        if result is True:
                            self.state = StepState.SUCCESS
                            return (self.state, "人工处理后成功")
                    print("  → 重试仍失败，继续等待或选择跳过/终止")
                elif cmd == 's':
                    self.state = StepState.SKIP
                    return (self.state, "用户手动跳过")
                elif cmd == 'f':
                    self.state = StepState.FAIL
                    return (self.state, "用户终止流程")
            except Exception:
                await asyncio.sleep(0.5)

        # 超时，跳过
        self.state = StepState.SKIP
        return (self.state, "人工介入超时，已跳过")


###############################################################################
#  运行结果
###############################################################################

class RunResult:
    """一次运行的完整结果"""
    def __init__(self):
        self.success = 0
        self.skip = 0
        self.fail = 0
        self.success_indices = []
        self.fail_indices = []
        self.skip_indices = []
        self.fatal = False
        self.total = 0


###############################################################################
#  主流程引擎
###############################################################################

class FlowEngine:
    """
    流程引擎 - 整合所有组件
    """

    def __init__(self, json_path: str, yaml_path: str = None):
        self.json_path = json_path
        self.yaml_path = yaml_path
        self.elements = []
        self.actions = {}
        self.event_bus = EventBus()
        self.cdp = CDPEngine(self.event_bus)
        self.state = FlowState.INIT
        self._pw = None
        self._context = None
        self.page = None
        self.vars_dict = {}
        self.human_config = HumanInterventionConfig()

        # 统计
        self.stats = {"success": 0, "skip": 0, "fail": 0}

        # 注册默认事件
        self._register_default_events()

    def _register_default_events(self):
        """注册默认日志事件"""

        @self.event_bus.on("step.start")
        def on_start(event, **data):
            print(f"\n  [{data['index']}] ▶ 开始: {data['step_name']}")

        @self.event_bus.on("step.success")
        def on_success(event, **data):
            print(f"      ✅ 成功")

        @self.event_bus.on("step.skip")
        def on_skip(event, **data):
            reason = data.get("reason", "")
            print(f"      ⏭️  跳过: {reason}")

        @self.event_bus.on("step.fail")
        def on_fail(event, **data):
            error = data.get("error", "")
            print(f"      ❌ 失败: {error}")

        @self.event_bus.on("step.waiting")
        def on_waiting(event, **data):
            delay = data.get("delay", 0)
            attempt = data.get("attempt", 0)
            print(f"      ⏳ 等待 {delay:.1f}s (第{attempt}次重试)", end="\r")

        @self.event_bus.on("step.retry")
        def on_retry(event, **data):
            a = data.get("attempt", 0)
            m = data.get("max_retries", 0)
            print(f"      🔄 重试 {a}/{m}")

        @self.event_bus.on("ocr.found")
        def on_ocr_found(event, **data):
            print(f"      👁️  OCR找到文字: \"{data.get('text','')[:20]}\" 坐标=({data.get('x',0)},{data.get('y',0)})")

        @self.event_bus.on("step.human_help")
        def on_human(event, **data):
            pass  # 由 _wait_human_intervention 处理

        @self.event_bus.on("step.parent")
        def on_parent(event, **data):
            print(f"      📦 父元素已捕获")

    # ── 加载 ──
    async def load(self):
        """加载 JSON + YAML + vars"""
        # JSON（兼容所有格式）
        def _flatten(raw):
            """展平 V10 包裹格式为平铺元素列表"""
            if isinstance(raw, dict) and "elements" in raw:
                return raw["elements"]
            if isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], dict) and "elements" in raw[0]:
                flat = []
                for wrapper in raw:
                    inner = wrapper.get("elements", [])
                    for el in inner:
                        if "step_name" not in el or not el.get("step_name"):
                            el["step_name"] = wrapper.get("metadata", {}).get("step_name", "unknown")
                        if "page_url" not in el or not el.get("page_url"):
                            el["page_url"] = wrapper.get("metadata", {}).get("page_url", "")
                        if "cleaned" not in el and "cleaned" in wrapper:
                            el["cleaned"] = wrapper["cleaned"]
                        flat.append(el)
                print(f"  ℹ️  检测到 V10 清洗格式，已展平 {len(flat)} 个元素")
                return flat
            if isinstance(raw, list):
                return raw
            raise ValueError(f"不支持的 JSON 格式: {type(raw)}")

        with open(self.json_path, 'r', encoding='utf-8') as f:
            self.elements = _flatten(json.load(f))
        print(f"  加载元素: {len(self.elements)} 个")

        # YAML
        if self.yaml_path is None:
            stem = Path(self.json_path).stem.replace("_cleaned", "")
            candidate = os.path.join(PROJECT_ROOT, f"actions_config_{stem}.yaml")
            if os.path.isfile(candidate):
                self.yaml_path = candidate

        if self.yaml_path and HAS_YAML:
            with open(self.yaml_path, 'r', encoding='utf-8') as f:
                data = _yaml.safe_load(f) or {}
            for item in data.get("actions", []):
                idx = item.get("index")
                if idx is not None:
                    self.actions[idx] = item.get("action", {})
            print(f"  加载动作: {len(self.actions)} 个")

        # vars
        vars_path = os.path.join(PROJECT_ROOT, "vars.yaml")
        if os.path.isfile(vars_path) and HAS_YAML:
            with open(vars_path, 'r', encoding='utf-8') as f:
                self.vars_dict = {k: v for k, v in (_yaml.safe_load(f) or {}).items()
                                  if isinstance(k, str)}
            print(f"  加载变量: {len(self.vars_dict)} 个")

    # ── 启动浏览器 ──
    async def _launch_browser(self):
        """启动 Playwright + 连接 CDP"""
        self._cleanup_chrome()

        self._pw = await async_playwright().start()
        launch_kwargs = {
            "user_data_dir": "playwright_profile",
            "channel": "chrome",
            "headless": False,
            "no_viewport": True,
            "locale": "zh-CN",
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--remote-debugging-port=9222",
            ],
        }
        self._context = await self._pw.chromium.launch_persistent_context(**launch_kwargs)
        self.page = await self._context.new_page()
        self.page.set_default_timeout(30000)

        # 连接 CDP
        await self.cdp.connect(self.page)

        print(f"  浏览器已启动 | CDP: {'在线' if self.cdp.connected else '离线'}")
        print(f"  🔌 CDP 调试: http://127.0.0.1:9222")

    def _cleanup_chrome(self):
        """清理残留进程"""
        import subprocess
        try:
            subprocess.run('taskkill /f /im chrome.exe 2>nul',
                           shell=True, capture_output=True, text=True)
        except Exception:
            pass

    async def _ensure_url(self, page, expected_url: str) -> bool:
        """
        确保当前页面 URL 匹配期望的 URL。
        如果实际 URL 与期望不同且期望不为空，跳转。
        返回 True（已跳转）或 False（已在正确页面）。
        """
        if not expected_url:
            return False
        try:
            actual = page.url
            # 用 startswith 比较，避免 query params 差异
            if actual.rstrip("/") == expected_url.rstrip("/"):
                return False
            if actual.startswith(expected_url):
                return False
        except Exception:
            pass

        resolved = self._resolve_vars(expected_url)
        print(f"      → 跳转到: {resolved}")
        await page.goto(resolved, wait_until="load", timeout=20000)
        await asyncio.sleep(2)
        return True

    def _resolve_vars(self, text: str) -> str:
        """解析变量"""
        def _replacer(m):
            return str(self.vars_dict.get(m.group(1), m.group(0)))
        return re.sub(r'\$\{(\w+)\}', _replacer, text)

    # ── 执行 ──
    async def run(self, keep_browser=False) -> RunResult:
        """
        执行整个流程。
        keep_browser=True 时浏览器保持打开，适用于连续执行模式。
        返回 RunResult 包含详细统计。
        """
        result = RunResult()

        await self.load()

        print(f"\n{'='*60}")
        print(f"  高级执行引擎")
        print(f"  CDP 引擎: {'开启' if HAS_PYPPETEER else '内置(Playwright)'}")
        print(f"  人工介入: {'开启' if self.human_config.enabled else '关闭'}")
        if keep_browser:
            print(f"  浏览器模式: 持续保持（不关闭）")
        print(f"{'='*60}")

        # 如果浏览器还没启动，启动
        if self.page is None:
            await self._launch_browser()
        else:
            print(f"  📌 复用已有浏览器会话")

        self.state = FlowState.RUNNING

        # 按 step_name 分组
        groups = OrderedDict()
        for i, item in enumerate(self.elements):
            sn = item["step_name"]
            if sn not in groups:
                groups[sn] = []
            groups[sn].append(i)

        runner = StepRunner(self.page, self.cdp, self.event_bus,
                            self.elements, self.vars_dict, self.human_config)

        result.total = len(self.elements)
        has_fatal = False
        iteration_success = 0
        iteration_skip = 0
        iteration_fail = 0

        try:
            # 初始导航到第一个页面
            first_url = self.elements[0].get("page_url", "")
            if first_url:
                resolved = self._resolve_vars(first_url)
                print(f"\n  → 导航到: {resolved}")
                await self.page.goto(resolved, wait_until="load", timeout=20000)
                await asyncio.sleep(2)

            last_navigated_url = None

            for group_idx, (step_name, indices) in enumerate(groups.items(), 1):
                if has_fatal:
                    print(f"\n  [{group_idx}/{len(groups)}] 区域: {step_name}")
                    print(f"      ⏭️  前置致命错误")
                    iteration_skip += len(indices)
                    for gi in indices:
                        result.skip_indices.append(gi)
                    continue

                first_item = self.elements[indices[0]]
                zone_url = first_item.get("page_url", "")
                navigated = await self._ensure_url(self.page, zone_url)
                if navigated:
                    runner.reset_parent()
                    if last_navigated_url is not None:
                        print(f"      🗑️  父元素容器已重置（跨页面）")
                    last_navigated_url = zone_url

                is_parent = "父元素" in step_name
                zone_label = "📦" if is_parent else "📍"
                runner.set_zone(step_name)

                parent_info = ""
                if runner.parent_locator is not None:
                    parent_info = " (父元素容器生效中)"
                print(f"\n  [{group_idx}/{len(groups)}] {zone_label} {step_name}{parent_info} ({len(indices)}元素)")

                for idx_in_zone, global_idx in enumerate(indices, 1):
                    item = self.elements[global_idx]
                    strategies = item.get("cleaned", {}).get("strategies", [])
                    action = self.actions.get(global_idx, self._auto_action(item))

                    sel = item.get("selectors", {})
                    tag = sel.get("tag", "")
                    text = (sel.get("text", "") or "")[:30]

                    step = StepAction(
                        index=global_idx,
                        step_name=step_name,
                        strategies=strategies,
                        action=action,
                        config=action.get("_config", {}),
                    )

                    ptag = " [容器内]" if runner.parent_locator is not None else ""
                    print(f"      └ [{idx_in_zone}/{len(indices)}] <{tag}> {text:25s} → {action.get('type','?')}{ptag}")

                    state, msg = await runner.run(step)

                    if state == StepState.SUCCESS:
                        iteration_success += 1
                        result.success_indices.append(global_idx)
                    elif state == StepState.SKIP:
                        iteration_skip += 1
                        result.skip_indices.append(global_idx)
                    elif state == StepState.FAIL:
                        iteration_fail += 1
                        result.fail_indices.append(global_idx)
                        if action.get("on_not_found", "fail") == "fail":
                            has_fatal = True

            # ── 统计 ──
            result.success = iteration_success
            result.skip = iteration_skip
            result.fail = iteration_fail
            result.fatal = has_fatal

            self._print_stats(result)

        except Exception as e:
            print(f"\n  ❌ 异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if not keep_browser:
                await self._cleanup()
            else:
                print(f"\n  📌 浏览器保持打开，等待下一轮执行...")

        return result

    def _print_stats(self, result: RunResult):
        """打印统计信息"""
        print(f"\n{'='*60}")
        print(f"  本轮执行完毕！")
        print(f"  ✅ 成功: {result.success}  ⏭️  跳过: {result.skip}  ❌ 失败: {result.fail}")
        net = result.success + result.fail
        if net > 0:
            print(f"  有效率: {result.success}/{net} ({result.success*100//net}%)")
        if result.fatal:
            print(f"  🛑 本轮有致命错误")
        total_done = result.success + result.skip + result.fail
        print(f"  总进度: {total_done}/{result.total}")
        print(f"{'='*60}")

    async def _cleanup(self):
        """清理资源（关闭浏览器、CDP等）"""
        await self.cdp.disconnect()
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw:
            await self._pw.stop()
        self.page = None
        self._context = None
        self._pw = None

    def _auto_action(self, item: dict) -> dict:
        """智能推荐默认动作"""
        sel = item.get("selectors", {})
        tag = sel.get("tag", "").lower()
        text = sel.get("text", "") or ""
        placeholder = sel.get("placeholder", "") or ""
        step_name = item.get("step_name", "")

        if "父元素" in step_name:
            return {"type": "locate_parent", "on_not_found": "fail"}
        if "是否可见" in step_name or "可见" in step_name:
            return {"type": "check_exists", "on_not_found": "skip"}
        if tag in ("input", "textarea"):
            return {"type": "fill", "value": "${INPUT_VALUE}", "clear_first": True, "on_not_found": "skip"}
        if tag in ("button", "a"):
            ws = "navigation" if any(k in text for k in ["登录", "提交", "确认", "保存", "确定"]) else "timeout"
            return {"type": "click", "on_not_found": "skip", "wait_strategy": ws}
        if tag == "select":
            return {"type": "select", "value": "", "on_not_found": "skip"}
        return {"type": "click", "on_not_found": "skip"}


###############################################################################
#  CLI
###############################################################################

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python advanced_runner.py <cleaned.json> [actions_config.yaml]")
        print()
        print("功能:")
        print("  · 双引擎: Playwright + CDP/Pyppeteer 深度搜索")
        print("  · 状态机: 定位→执行→等待→重试→人工介入→跳过/失败")
        print("  · 长连接: CDP Session 持续在线，实时 DOM 检查")
        print("  · 错误恢复: 指数退避重试 + 人工介入")
        print("  · 调试: 失败自动截屏 + DOM 快照")
        print()
        print("连续模式:")
        print("  python advanced_runner.py --continuous <cleaned.json> [yaml]")
        print("  浏览器保持打开，可反复重试失败的步骤")
        sys.exit(1)

    # 检测 --continuous 标志
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    json_path = args[0] if args else None
    yaml_path = args[1] if len(args) > 1 else None
    continuous = "--continuous" in flags

    if not json_path or not os.path.isfile(json_path):
        print(f"文件不存在或未指定: {json_path}")
        sys.exit(1)

    engine = FlowEngine(json_path, yaml_path)

    try:
        if continuous:
            asyncio.run(_run_continuous(engine))
        else:
            asyncio.run(engine.run())
    except KeyboardInterrupt:
        print("\n\n  用户中断")
    except Exception as e:
        print(f"\n  引擎异常: {e}")
        import traceback
        traceback.print_exc()


async def _run_continuous(engine: FlowEngine):
    """连续执行模式：保持浏览器，反复重试失败步骤"""
    from copy import deepcopy

    print(f"\n{'='*60}")
    print(f"  🔄 连续执行模式")
    print(f"  浏览器将保持打开，可反复重试")
    print(f"{'='*60}")

    # 先跑第一轮（启动浏览器）
    result = await engine.run(keep_browser=True)

    # 保存原始索引范围
    all_indices = set(range(result.total))

    while True:
        # 计算进度
        done = len(result.success_indices) + len(result.skip_indices)
        failed = set(result.fail_indices)
        remaining = all_indices - set(result.success_indices) - set(result.skip_indices)

        print(f"\n{'='*60}")
        print(f"  🔄 连续执行菜单")
        print(f"  总进度: {done}/{result.total}  |  成功: {len(result.success_indices)}  |  失败: {len(result.fail_indices)}")
        if failed:
            print(f"  待重试索引: {sorted(failed)}")
        print(f"{'='*60}")
        print(f"  r — 重试失败的 {len(failed)} 个元素")
        print(f"  a — 全部重新执行 ({result.total} 个)")
        print(f"  s — 跳过所有失败，标记完成")
        print(f"  h — 人工检查（浏览器保持，等待你操作后按回车）")
        print(f"  q — 退出并关闭浏览器")
        print(f"  {'─'*40}")

        # 读用户输入
        loop = asyncio.get_running_loop()

        def _read_input():
            import sys, select
            if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                return sys.stdin.readline().strip().lower()
            return None

        cmd = None
        while cmd is None:
            cmd = await loop.run_in_executor(None, _read_input)
            if cmd is None:
                await asyncio.sleep(0.3)

        if cmd == 'q':
            print("  → 退出并关闭浏览器")
            await engine._cleanup()
            break

        elif cmd == 's':
            print("  → 跳过所有失败，标记为完成")
            break

        elif cmd == 'r':
            if not failed:
                print("  → 没有需要重试的步骤")
                continue
            print(f"  → 重试 {len(failed)} 个失败元素...")
            # 单步重试失败的元素
            new_result = await _retry_indices(engine, sorted(failed))
            result.fail_indices = new_result.fail_indices
            result.success_indices.extend(new_result.success_indices)

        elif cmd == 'a':
            print(f"  → 全部重新执行...")
            engine.state = FlowState.RUNNING
            # 重置 runner （已经跨了一轮，需要重设）
            new_result = await engine.run(keep_browser=True)
            result = new_result

        elif cmd == 'h':
            print("  → 人工检查模式，浏览器保持打开")
            print("  请手动操作页面，操作完成后按回车继续...")
            await loop.run_in_executor(None, input, "  按回车回到菜单...")
            continue

        else:
            print(f"  未知命令: {cmd}")


async def _retry_indices(engine: FlowEngine, indices: list) -> RunResult:
    """只重试指定的索引列表"""
    from collections import OrderedDict
    from core.selector import robust_locate

    result = RunResult()
    result.total = len(indices)

    # 按 step_name 分组（只取需要重试的索引）
    groups = OrderedDict()
    for idx in indices:
        if idx >= len(engine.elements):
            continue
        sn = engine.elements[idx]["step_name"]
        if sn not in groups:
            groups[sn] = []
        groups[sn].append(idx)

    runner = StepRunner(engine.page, engine.cdp, engine.event_bus,
                        engine.elements, engine.vars_dict, engine.human_config)

    print(f"  重试 {len(indices)} 个元素, {len(groups)} 个区域")

    for group_idx, (step_name, idx_list) in enumerate(groups.items(), 1):
        print(f"\n    [{group_idx}/{len(groups)}] {step_name}")

        for ei, global_idx in enumerate(idx_list, 1):
            item = engine.elements[global_idx]
            strategies = item.get("cleaned", {}).get("strategies", [])
            action = engine.actions.get(global_idx, engine._auto_action(item))

            sel = item.get("selectors", {})
            tag = sel.get("tag", "")
            text = (sel.get("text", "") or "")[:25]

            step = StepAction(global_idx, step_name, strategies, action, {})
            print(f"      └ [{ei}/{len(idx_list)}] <{tag}> {text} → {action.get('type','?')}")

            state, msg = await runner.run(step)

            if state == StepState.SUCCESS:
                result.success += 1
                result.success_indices.append(global_idx)
            elif state == StepState.SKIP:
                result.skip += 1
                result.skip_indices.append(global_idx)
            elif state == StepState.FAIL:
                result.fail += 1
                result.fail_indices.append(global_idx)

    result.fatal = False
    return result


if __name__ == "__main__":
    main()
