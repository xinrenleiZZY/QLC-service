"""
run_flow_steps.py - 流程执行器（区域控制 + 父元素定位）
======================================================

核心设计:
  1. 区域控制 —— 按 step_name 分组，每个步骤组就是一个"区域/页面"
  2. 父元素定位 —— "XXX父元素" 作为容器，后续子元素在其中相对定位
  3. 页面导航 —— page_url 变化时自动跳转

用法:
    python run_flow_steps.py <cleaned.json> [actions_config.yaml]
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from collections import OrderedDict

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

try:
    import yaml as _yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from playwright.async_api import async_playwright
from core.selector import robust_locate


# ============================================================
#  变量解析
# ============================================================

def _load_vars() -> dict:
    vars_path = os.path.join(PROJECT_ROOT, "vars.yaml")
    if not os.path.isfile(vars_path) or not HAS_YAML:
        return {}
    with open(vars_path, 'r', encoding='utf-8') as f:
        data = _yaml.safe_load(f) or {}
    return {k: v for k, v in data.items() if isinstance(k, str)}


def _resolve_vars(text: str, vars_dict: dict) -> str:
    def _replacer(m):
        var_name = m.group(1)
        return str(vars_dict.get(var_name, m.group(0)))
    return re.sub(r'\$\{(\w+)\}', _replacer, text)


# ============================================================
#  加载配置
# ============================================================

def _load_actions(yaml_path: str) -> dict:
    """加载动作配置，返回 { index: action_config }"""
    result = {"page_url": "", "close_browser": True, "actions": {}}
    if not os.path.isfile(yaml_path) or not HAS_YAML:
        return result
    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = _yaml.safe_load(f) or {}
    result["page_url"] = data.get("page_url", "")
    result["close_browser"] = data.get("close_browser", True)
    for item in data.get("actions", []):
        idx = item.get("index")
        if idx is not None:
            result["actions"][idx] = item.get("action", {})
    return result


def _group_elements(elements: list) -> OrderedDict:
    """按 step_name 分组，保持原始顺序"""
    groups = OrderedDict()
    for item in elements:
        sn = item["step_name"]
        if sn not in groups:
            groups[sn] = []
        groups[sn].append(item)
    return groups


# ============================================================
#  智能推荐（默认行为）
# ============================================================

def _auto_action(item: dict) -> dict:
    """根据元素属性推荐默认动作"""
    sel = item.get("selectors", {})
    tag = sel.get("tag", "").lower()
    text = sel.get("text", "") or ""
    placeholder = sel.get("placeholder", "") or ""
    step_name = item.get("step_name", "")

    # 父元素 → 仅定位作为容器
    if "父元素" in step_name:
        return {"type": "locate_parent", "on_not_found": "fail"}

    # 检测类
    if "是否可见" in step_name or "可见" in step_name:
        return {"type": "check_exists", "on_not_found": "skip"}

    if tag in ("input", "textarea"):
        return {"type": "fill",
                "value": "${INPUT_VALUE}",
                "clear_first": True,
                "on_not_found": "fail"}
    elif tag in ("button", "a"):
        ws = "navigation" if any(k in text for k in ["登录", "提交", "确认", "保存", "确定"]) else "timeout"
        return {"type": "click", "on_not_found": "fail", "wait_strategy": ws}
    elif tag == "select":
        return {"type": "select", "value": "", "on_not_found": "fail"}
    elif tag in ("span", "li", "div"):
        # 可能是可点击项
        return {"type": "click", "on_not_found": "skip"}
    else:
        return {"type": "check_exists", "on_not_found": "skip"}


# ============================================================
#  定位引擎（区域控制版）
# ============================================================

async def _locate_with_retry(page, strategies: list,
                             parent_locator=None,
                             max_retries: int = 5,
                             retry_delay: float = 1.0):
    """
    带区域控制的定位。
    parent_locator: 父元素容器，不为 None 时在其内部定位
    """
    for attempt in range(1, max_retries + 1):
        loc = await robust_locate(page, strategies, parent_locator=parent_locator)
        if loc is not None:
            try:
                if await loc.is_visible():
                    return loc
            except:
                return loc  # 即使不可见也返回
        if attempt < max_retries:
            await asyncio.sleep(retry_delay)
    return None


# ============================================================
#  执行引擎（区域控制版）
# ============================================================

async def _execute(page, strategies: list, action: dict, vars_dict: dict,
                   parent_locator=None) -> tuple:
    """
    执行动作。
    返回: (True/False/"skip", message)
    """

    # ── locate_parent 特殊处理 ──
    if action.get("type") == "locate_parent":
        loc = await _locate_with_retry(page, strategies, parent_locator=None)
        if loc is None:
            on_nf = action.get("on_not_found", "fail")
            return ("skip" if on_nf == "skip" else False,
                    "父元素未找到" + ("（已跳过）" if on_nf == "skip" else ""))
        return ("parent", loc)  # 返回 locator 给调用方

    # ── 检测类 ──
    if action.get("type") in ("check_exists", "check_visible"):
        loc = await _locate_with_retry(page, strategies, parent_locator)
        if loc is None:
            return "skip", "元素不存在（已跳过）"
        if action["type"] == "check_visible":
            try:
                if await loc.is_visible():
                    return True, "元素可见"
                else:
                    return "skip", "元素存在但不可见（已跳过）"
            except:
                return "skip", "检测异常（已跳过）"
        return True, "元素存在"

    # ── 常规操作：先定位 ──
    loc = await _locate_with_retry(page, strategies, parent_locator)
    if loc is None:
        on_nf = action.get("on_not_found", "fail")
        if on_nf == "skip":
            return "skip", "元素未找到（已跳过）"
        return False, "定位失败（必须找到但未找到）"

    # ── 操作前等待 ──
    wait_before = action.get("wait_before", 0.3)
    if wait_before > 0:
        await asyncio.sleep(wait_before)

    action_type = action.get("type", "click")

    try:
        if action_type == "click":
            await loc.click()
        elif action_type == "fill":
            raw_value = action.get("value", "")
            value = _resolve_vars(raw_value, vars_dict)
            if action.get("clear_first", True):
                await loc.fill("")
            await loc.fill(value)
        elif action_type == "wait_visible":
            await loc.wait_for(state="visible", timeout=10000)
        elif action_type == "hover":
            await loc.hover()
        elif action_type == "select":
            raw_value = action.get("value", "")
            value = _resolve_vars(raw_value, vars_dict)
            await loc.select_option(value)
        elif action_type == "scroll_to":
            await loc.scroll_into_view_if_needed()
        elif action_type == "screenshot":
            name = action.get("screenshot_name", f"shot_{id(loc)}")
            os.makedirs("screenshots", exist_ok=True)
            await loc.screenshot(path=f"screenshots/{name}.png")
        else:
            await loc.click()
    except Exception as e:
        if action.get("on_not_found") == "skip":
            return "skip", f"操作异常已跳过: {e}"
        return False, str(e)

    # ── 操作后等待 ──
    if action_type not in ("scroll_to", "screenshot"):
        ws = action.get("wait_strategy", "timeout")
        try:
            if ws == "navigation":
                await page.wait_for_load_state("load", timeout=15000)
            elif ws == "element_appear":
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except:
            pass
        wa = action.get("wait_after", 0.5)
        if wa > 0:
            await asyncio.sleep(wa)

    return True, "成功"


# ============================================================
#  IF 条件评估
# ============================================================

async def _locate_by_index(page, elements, idx: int, parent_locator=None):
    """按全局索引定位元素"""
    if idx < 0 or idx >= len(elements):
        return None
    item = elements[idx]
    strategies = item.get("cleaned", {}).get("strategies", [])
    if not strategies:
        return None
    return await _locate_with_retry(page, strategies, parent_locator)


async def _evaluate_if(page, elements, if_config: dict, parent_locator=None) -> bool:
    """
    评估 IF 条件是否满足。
    返回 True=条件满足(应执行) / False=条件不满足(应跳过)
    """
    condition = if_config.get("condition", "")
    ref_idx = if_config.get("ref_index")

    if not condition or ref_idx is None:
        return True  # 无条件，直接执行

    # 定位引用元素
    ref_loc = await _locate_by_index(page, elements, ref_idx, parent_locator)
    ref_exists = ref_loc is not None

    if condition == "element_exists":
        return ref_exists
    elif condition == "element_not_exists":
        return not ref_exists
    else:
        return True


# ============================================================
#  主流程
# ============================================================

def _cleanup_chrome():
    """清理残留的 Chrome 进程，释放用户数据目录锁"""
    import subprocess
    try:
        # 杀掉由 Playwright 启动的 Chrome 进程（带 --remote-debugging-pipe 标志的）
        result = subprocess.run(
            'taskkill /f /im chrome.exe 2>nul',
            shell=True, capture_output=True, text=True
        )
        if result.returncode == 0:
            print("  🧹 已清理残留 Chrome 进程")
    except Exception:
        pass


async def _launch_with_retry(p, max_retries=2):
    """启动浏览器，失败时重试"""
    launch_kwargs = {
        "user_data_dir": "playwright_profile",
        "channel": "chrome",
        "headless": False,
        "no_viewport": True,
        "locale": "zh-CN",
        "args": [
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    for attempt in range(1, max_retries + 1):
        try:
            return await p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            if attempt < max_retries:
                print(f"  ⚠️  浏览器启动失败 (第{attempt}次), 重试中...")
                _cleanup_chrome()
                await asyncio.sleep(2)
            else:
                raise e
    raise RuntimeError("浏览器启动失败")


async def run(json_path: str, yaml_path: str = None):
    """执行整个流程"""

    # ── 1. 加载数据 ──
    print(f"\n{'='*60}")
    print(f"  加载 JSON: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        elements = json.load(f)
    print(f"  元素总数: {len(elements)}")

    # 自动查找 YAML
    if yaml_path is None:
        stem = Path(json_path).stem.replace("_cleaned", "")
        candidate = os.path.join(PROJECT_ROOT, f"actions_config_{stem}.yaml")
        if os.path.isfile(candidate):
            yaml_path = candidate

    config = _load_actions(yaml_path) if yaml_path else {"page_url": "", "close_browser": True, "actions": {}}
    actions_dict = config["actions"]
    close_browser = config.get("close_browser", True)
    has_actions = bool(actions_dict)

    # ── 2. 按 step_name 分组（区域划分） ──
    groups = _group_elements(elements)
    print(f"  步骤组: {len(groups)} 个区域")
    print(f"  动作配置: {'有 (' + str(len(actions_dict)) + ' 个)' if has_actions else '无（使用智能默认值）'}")
    print(f"{'='*60}")

    # ── 3. 启动浏览器（先清理残留进程） ──
    _cleanup_chrome()
    p = await async_playwright().start()
    context = await _launch_with_retry(p)
    page = await context.new_page()
    page.set_default_timeout(30000)

    vars_dict = _load_vars()
    current_url = None
    success_count = 0
    skip_count = 0
    fail_count = 0
    has_fatal = False

    # 区域控制：父元素定位器栈
    parent_stack = {}  # step_name -> Locator
    active_parent = None

    try:
        # ── 4. 逐区执行 ──
        group_idx = 0
        for step_name, step_elements in groups.items():
            group_idx += 1
            if has_fatal:
                print(f"\n  [{group_idx}/{len(groups)}] 🛑 区域: {step_name}")
                print(f"      ⏭️  前置致命失败，跳过此区域")
                skip_count += len(step_elements)
                continue

            first_item = step_elements[0]
            page_url = first_item.get("page_url", "")

            # ── 页面导航 ──
            if page_url and page_url != current_url:
                resolved_url = _resolve_vars(page_url, vars_dict)
                print(f"\n  → 跳转到: {resolved_url}")
                await page.goto(resolved_url, wait_until="load", timeout=20000)
                await asyncio.sleep(2)
                current_url = page_url

            # ── 判断区域类型 ──
            is_parent = "父元素" in step_name
            zone_label = "【父元素】" if is_parent else "【区域】"

            print(f"\n  [{group_idx}/{len(groups)}] {zone_label} {step_name}")
            print(f"      ├ 页面: {page_url}")
            print(f"      ├ 元素数: {len(step_elements)}")

            # ── 执行区域内每个元素 ──
            for ei, item in enumerate(step_elements):
                global_idx = elements.index(item)
                strategies = item.get("cleaned", {}).get("strategies", [])

                # 获取动作配置（优先用户配置，其次智能默认）
                if has_actions and global_idx in actions_dict:
                    action = actions_dict[global_idx]
                else:
                    action = _auto_action(item)

                sel = item.get("selectors", {})
                tag = sel.get("tag", "")
                text = (sel.get("text", "") or "")[:30]

                atype_label = action.get("type", "?")

                # ── IF 条件检查 ──
                skip_reason = None
                if action.get("if") and isinstance(action["if"], dict):
                    if_met = await _evaluate_if(page, elements, action["if"], active_parent)
                    cond_label = action["if"].get("condition", "?")
                    ref_idx = action["if"].get("ref_index", "?")
                    if not if_met:
                        skip_reason = f"IF 条件不满足 ({cond_label} #ref={ref_idx})"
                    else:
                        print(f"      └ 条件满足: {cond_label} #ref={ref_idx}")

                if skip_reason:
                    print(f"            ⏭️  {skip_reason}")
                    skip_count += 1
                else:
                    # ── 执行 ──
                    result, msg = await _execute(
                        page, strategies, action, vars_dict,
                        parent_locator=active_parent
                    )

                    if result is True:
                        print(f"            ✅ {msg}")
                        success_count += 1
                        try:
                            loc = await _locate_with_retry(page, strategies, active_parent)
                            if loc:
                                await loc.highlight()
                        except:
                            pass

                    elif result == "skip":
                        print(f"            ⏭️  {msg}")
                        skip_count += 1

                    elif result == "parent":
                        # 保存父元素定位器作为后续子元素的容器
                        active_parent = msg
                        parent_stack[step_name] = msg
                        print(f"            📦 已保存为父元素容器，后续元素在其内部定位")
                        success_count += 1

                    else:
                        on_nf = action.get("on_not_found", "fail")
                        if on_nf == "fail":
                            print(f"            🛑 {msg}（必须找到，流程终止）")
                            fail_count += 1
                            has_fatal = True
                            break  # 退出当前区域
                        else:
                            print(f"            ❌ {msg}")
                            fail_count += 1

        # ── 统计 ──
        print(f"\n{'='*60}")
        total = success_count + skip_count + fail_count
        net_total = total - skip_count
        print(f"  执行完毕！")
        print(f"  ✅ 成功: {success_count}")
        print(f"  ⏭️  跳过: {skip_count}")
        print(f"  ❌ 失败: {fail_count}")
        if net_total > 0:
            print(f"  有效率: {success_count}/{net_total} ({success_count*100//net_total}%)")
        if has_fatal:
            print(f"  🛑 流程因致命错误终止")
        print(f"{'='*60}")

        if close_browser:
            await asyncio.sleep(3)
        else:
            print("浏览器保持打开...")

    except Exception as e:
        print(f"\n  ❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        if not close_browser:
            await asyncio.sleep(3600)
    finally:
        if close_browser:
            await context.close()
            await p.stop()
        else:
            try:
                await asyncio.sleep(3600)
            except:
                pass
            finally:
                await context.close()
                await p.stop()


# ============================================================
#  CLI
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python run_flow_steps.py <cleaned.json> [actions_config.yaml]")
        print()
        print("示例:")
        print("  python run_flow_steps.py lingxing_elements-批量创建关键词流程_cleaned.json")
        sys.exit(1)

    json_path = sys.argv[1]
    if not os.path.isfile(json_path):
        print(f"文件不存在: {json_path}")
        sys.exit(1)

    yaml_path = sys.argv[2] if len(sys.argv) > 2 else None
    if yaml_path and not os.path.isfile(yaml_path):
        yaml_path = None

    asyncio.run(run(json_path, yaml_path))


if __name__ == "__main__":
    main()
