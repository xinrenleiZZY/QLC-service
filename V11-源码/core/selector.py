"""智能选择器 + 策略执行引擎 - 稳定不变"""

from typing import List, Dict, Optional
from playwright.async_api import Page, Locator


async def robust_locate(page: Page, strategies: List[dict], parent_locator=None, timeout=5000):
    """按顺序尝试策略列表，返回第一个可定位且可见的元素"""
    container = parent_locator or page
    for strategy in strategies:
        loc = await execute_strategy(container, strategy)
        if loc:
            try:
                if await loc.is_visible():
                    return loc
            except:
                continue
    return None


async def execute_strategy(container, strategy: dict):
    """执行单条定位策略，支持锚定"""
    try:
        if strategy.get("type") == "anchored":
            anchor = strategy["anchor"]
            target = strategy["target"]
            anchor_loc = await _locate_anchor(container, anchor)
            if anchor_loc is None:
                return None
            return await _execute_simple(anchor_loc, target)
        else:
            return await _execute_simple(container, strategy)
    except Exception:
        return None


async def _locate_anchor(container, anchor: dict):
    """定位锚点容器"""
    atype = anchor["type"]
    avalue = anchor["value"]
    if atype == "role":
        loc = container.get_by_role(avalue)
        if await loc.count() > 0:
            return loc.last
    elif atype == "id":
        # 支持前缀匹配：如果尝试精确匹配失败且值不含特殊字符，尝试 [id^="xxx"]
        loc = container.locator(f'#{avalue}')
        if await loc.count() > 0:
            return loc.last
        # CSS 中 id 如果有末尾数字是动态的，尝试前缀匹配
        if avalue.rstrip('-').isalnum() or avalue.count('-') > 0:
            prefix_loc = container.locator(f'[id^="{avalue}"]')
            if await prefix_loc.count() > 0:
                return prefix_loc.last
    elif atype == "aria_label":
        return container.locator(f'[aria-label="{avalue}"]')
    elif atype == "css":
        loc = container.locator(avalue)
        if await loc.count() > 0:
            return loc.last
    return None


async def _execute_simple(container, strategy: dict) -> Optional[Locator]:
    """执行简单策略"""
    stype = strategy["type"]
    value = strategy.get("value", "")

    if stype == "text":
        loc = container.get_by_text(value, exact=True)
    elif stype == "placeholder":
        loc = container.get_by_placeholder(value)
    elif stype == "aria_label":
        loc = container.locator(f'[aria-label="{value}"]')
    elif stype == "title":
        loc = container.locator(f'[title="{value}"]')
    elif stype == "name":
        loc = container.locator(f'[name="{value}"]')
    elif stype == "id":
        loc = container.locator(f'#{value}')
    elif stype == "css":
        loc = container.locator(value)
    elif stype == "role":
        if '[name="' in value:
            role_name = value.split('[name="')[-1].rstrip('"]')
            loc = container.get_by_role(value.split('[')[0], name=role_name)
        else:
            loc = container.get_by_role(value)
    elif stype == "attribute":
        loc = container.locator(value)
    else:
        return None

    if await loc.count() > 0:
        return loc.first
    return None


async def smart_click(page: Page, strategies: List[dict]) -> bool:
    """智能点击"""
    loc = await robust_locate(page, strategies)
    if loc:
        await loc.click()
        return True
    return False


async def smart_fill(page: Page, strategies: List[dict], value: str) -> bool:
    """智能填写"""
    loc = await robust_locate(page, strategies)
    if loc:
        await loc.fill(value)
        return True
    return False