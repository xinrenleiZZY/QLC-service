"""
run_custom_steps.py - 定制化步骤执行器 v2
========================================

用法:
    python run_custom_steps.py <cleaned.json> [actions_config.yaml]

能力:
    1. 按配置执行 click/fill/wait_visible/hover/select
    2. 找不到时行为: fail(必须找到) / skip(可跳过)
    3. wait_for_element: 等待元素动态出现（弹窗等）
    4. 三种等待策略: timeout / navigation / element_appear
    5. 变量替换: ${VAR_NAME} → vars.yaml
    6. 全局配置: 执行完毕后是否关闭浏览器
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

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
    """加载 vars.yaml"""
    vars_path = os.path.join(PROJECT_ROOT, "vars.yaml")
    if not os.path.isfile(vars_path):
        return {}
    if not HAS_YAML:
        print("  \u26a0\ufe0f  PyYAML 未安装, 跳过 vars.yaml")
        return {}
    with open(vars_path, 'r', encoding='utf-8') as f:
        data = _yaml.safe_load(f) or {}
    return {k: v for k, v in data.items() if isinstance(k, str)}


def _resolve_vars(text: str, vars_dict: dict) -> str:
    """将 ${VAR_NAME} 替换为实际值"""
    def _replacer(m):
        var_name = m.group(1)
        return str(vars_dict.get(var_name, m.group(0)))
    return re.sub(r'\$\{(\w+)\}', _replacer, text)


# ============================================================
#  加载配置
# ============================================================

def _load_actions(yaml_path: str) -> dict:
    """
    加载 actions YAML。
    返回 {
        "page_url": "...",
        "close_browser": True/False,
        "actions": { index: action_config }
    }
    """
    result = {
        "page_url": "",
        "close_browser": True,
        "actions": {},
    }
    if not os.path.isfile(yaml_path):
        return result
    if not HAS_YAML:
        print("  \u26a0\ufe0f  PyYAML 未安装, 跳过动作配置")
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


# ============================================================
#  定位引擎(增强版)
# ============================================================

async def _robust_locate_with_retry(page, strategies: list,
                                    max_retries: int = 5,
                                    retry_delay: float = 1.0):
    """带重试的定位"""
    for attempt in range(1, max_retries + 1):
        loc = await robust_locate(page, strategies)
        if loc is not None:
            return loc
        if attempt < max_retries:
            await asyncio.sleep(retry_delay)
    return None


# ============================================================
#  动作执行引擎(增强版)
# ============================================================

async def _execute_action(page, strategies: list, action: dict, vars_dict: dict):
    """
    执行一个动作，返回 (成功/失败, 消息/异常信息)。
    新增能力:
      - on_not_found: fail/skip
      - wait_for_element: 先等待元素出现再定位
    """

    # ── 0. 等待元素出现（可选） ──
    if action.get("wait_for_element", False):
        wait_timeout = action.get("wait_timeout", 10) * 1000  # 转毫秒
        # 用 CSS 选择器尝试等待（取 strategies 里的第一个 css/text 等）
        wait_selector = _pick_wait_selector(strategies)
        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector,
                                             timeout=wait_timeout)
            except Exception:
                # 等了也没出现，继续往下走，让定位重试兜底
                pass

    action_type = action.get("type", "click")

    # ── 检测类操作：不需要定位，有特殊逻辑 ──
    if action_type == "check_exists":
        loc = await _robust_locate_with_retry(page, strategies)
        if loc is not None:
            return True, "元素存在"
        else:
            return "skip", "元素不存在（已跳过）"

    if action_type == "check_visible":
        loc = await _robust_locate_with_retry(page, strategies)
        if loc is not None:
            try:
                visible = await loc.is_visible()
                if visible:
                    return True, "元素可见"
                else:
                    return "skip", "元素存在但不可见（已跳过）"
            except Exception:
                return "skip", "检测可见性异常（已跳过）"
        else:
            return "skip", "元素不存在（已跳过）"

    # ── 常规操作：先定位 ──
    loc = await _robust_locate_with_retry(page, strategies)
    if loc is None:
        on_not_found = action.get("on_not_found", "fail")
        if on_not_found == "skip":
            return "skip", "元素未找到，已跳过"
        else:
            return False, "定位失败（必须找到但未找到）"

    # ── 操作前等待 ──
    wait_before = action.get("wait_before", 0.3)
    if wait_before > 0:
        await asyncio.sleep(wait_before)

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
            screenshot_name = action.get("screenshot_name", f"screenshot_{id(loc)}")
            os.makedirs("screenshots", exist_ok=True)
            path = os.path.join("screenshots", f"{screenshot_name}.png")
            await loc.screenshot(path=path)

        else:
            await loc.click()

    except Exception as e:
        if action.get("on_not_found") == "skip":
            return "skip", f"操作异常已跳过: {e}"
        return False, str(e)

    # ── 操作后等待策略（scroll_to/screenshot 不需要） ──
    if action_type not in ("scroll_to", "screenshot"):
        wait_strategy = action.get("wait_strategy", "timeout")
        try:
            if wait_strategy == "navigation":
                await page.wait_for_load_state("load", timeout=15000)
            elif wait_strategy == "element_appear":
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        wait_after = action.get("wait_after", 0.5)
        if wait_after > 0:
            await asyncio.sleep(wait_after)

    return True, "成功"


def _pick_wait_selector(strategies: list) -> str:
    """
    从 strategies 中提取一个合适的 CSS 选择器用于 wait_for_selector。
    优先顺序: css > text > placeholder > name > id
    """
    for s in strategies:
        stype = s.get("type", "")
        value = s.get("value", "")
        if stype == "css" and value:
            return value
        if stype == "text" and value:
            # text 转 CSS 选择器不太准确，返回 None 让默认重试兜底
            pass
        if stype == "placeholder" and value:
            return f'[placeholder="{value}"]'
        if stype == "name" and value:
            return f'[name="{value}"]'
        if stype == "id" and value:
            return f"#{value}"
    return None


# ============================================================
#  主执行逻辑
# ============================================================

async def run(json_path: str, yaml_path: str = None):
    """执行整个流程"""

    # ── 1. 加载数据 ──
    print(f"\n{'='*60}")
    print(f"  加载 JSON: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        elements = json.load(f)
    print(f"  元素数量: {len(elements)}")

    # 自动查找 YAML
    if yaml_path is None:
        stem = Path(json_path).stem.replace("_cleaned", "")
        candidate = os.path.join(PROJECT_ROOT, f"actions_config_{stem}.yaml")
        if os.path.isfile(candidate):
            yaml_path = candidate

    config = _load_actions(yaml_path) if yaml_path else {
        "page_url": "", "close_browser": True, "actions": {}
    }
    actions_dict = config["actions"]
    close_browser = config.get("close_browser", True)

    if yaml_path:
        print(f"  动作配置: {yaml_path}  ({len(actions_dict)} 个已配置)")
        print(f"  关闭浏览器: {'是' if close_browser else '否, 保持打开'} ")
    else:
        print(f"  动作配置: 无 (仅定位验证)")

    vars_dict = _load_vars()
    if vars_dict:
        print(f"  变量加载: {len(vars_dict)} 个变量可用")
    print(f"{'='*60}")

    # ── 2. 启动浏览器 ──
    p = await async_playwright().start()
    context = await p.chromium.launch_persistent_context(
        user_data_dir="playwright_profile",
        channel="chrome",
        headless=False,
        no_viewport=True,
        locale="zh-CN",
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
    )
    page = await context.new_page()
    page.set_default_timeout(30000)

    success_count = 0
    skip_count = 0
    fail_count = 0
    has_critical_failure = False
    current_url = None

    try:
        # ── 3. 导航到页面 ──
        target_url = config.get("page_url") or elements[0].get("page_url", "")
        if target_url:
            target_url = _resolve_vars(target_url, vars_dict)
            print(f"\n  → 导航到: {target_url}")
            await page.goto(target_url, wait_until="load", timeout=20000)
            await asyncio.sleep(2)
            current_url = target_url

        # ── 4. 遍历元素 ──
        for i, item in enumerate(elements):
            # 如果之前有致命失败，直接跳过后续所有
            if has_critical_failure:
                step_name = item.get("step_name", f"步骤{i+1}")
                print(f"\n  [{i+1}/{len(elements)}] 步骤: {step_name}")
                print(f"      ⏭️  前置步骤失败，跳过")
                skip_count += 1
                continue

            step_name = item.get("step_name", f"步骤{i+1}")
            strategies = item.get("cleaned", {}).get("strategies", [])
            reliability = item.get("cleaned", {}).get("reliability", "unknown")
            selectors = item.get("selectors", {})
            tag = selectors.get("tag", "")
            text = selectors.get("text", "")
            placeholder = selectors.get("placeholder", "")

            # URL 导航
            page_url = item.get("page_url", "")
            if page_url and page_url != current_url:
                page_url = _resolve_vars(page_url, vars_dict)
                print(f"\n  → 导航到: {page_url}")
                await page.goto(page_url, wait_until="load", timeout=20000)
                await asyncio.sleep(2)
                current_url = page_url

            # ── 5. 打印步骤信息 ──
            action_cfg = actions_dict.get(i, {})
            has_action = bool(action_cfg)

            print(f"\n  [{i+1}/{len(elements)}] 步骤: {step_name}")
            print(f"      标签: <{tag}>  |  文本: {(text or '')[:50]}")
            print(f"      placeholder: {placeholder or '无'}  |  可靠性: {reliability}")

            if has_action:
                atype = action_cfg.get("type", "?")
                not_found_mode = action_cfg.get("on_not_found", "fail")
                we = "是" if action_cfg.get("wait_for_element") else "否"
                desc = f"{atype}"
                if atype == "fill":
                    desc += f" = \"{action_cfg.get('value', '')}\""
                desc += f"  |  找不到: {not_found_mode}"
                desc += f"  |  等出现: {we}"
                desc += f"  |  后: {action_cfg.get('wait_after', 0)}s"
                print(f"      动作: {desc}")
            else:
                print(f"      动作: 未配置 → 仅验证定位")

            # ── 6. 执行 ──
            if has_action:
                result, msg = await _execute_action(page, strategies,
                                                    action_cfg, vars_dict)

                if result is True:
                    print(f"      ✅ {msg}")
                    success_count += 1
                    try:
                        loc = await robust_locate(page, strategies)
                        if loc:
                            await loc.highlight()
                    except:
                        pass

                elif result == "skip":
                    print(f"      ⏭️  {msg}")
                    skip_count += 1

                else:
                    not_found_mode = action_cfg.get("on_not_found", "fail")
                    if not_found_mode == "fail":
                        print(f"      🛑 致命失败: {msg}")
                        print(f"      → 此元素标记为【必须找到】，流程终止")
                        fail_count += 1
                        has_critical_failure = True
                    else:
                        print(f"      ❌ 失败: {msg}")
                        fail_count += 1
            else:
                # 无配置 → 仅验证定位
                loc = await robust_locate(page, strategies)
                if loc:
                    print(f"      ✅ 定位成功（仅验证）")
                    try:
                        await loc.highlight()
                    except:
                        pass
                    success_count += 1
                else:
                    print(f"      ❌ 定位失败")
                    fail_count += 1

        # ── 结果统计 ──
        print(f"\n{'='*60}")
        total = success_count + fail_count + skip_count
        print(f"  执行完毕！")
        print(f"  ✅ 成功: {success_count}  |  ⏭️  跳过: {skip_count}  |  ❌ 失败: {fail_count}")
        print(f"  成功率: {success_count}/{total - skip_count} (排除跳过)")
        if has_critical_failure:
            print(f"  🛑 流程因致命错误终止")
        if skip_count > 0:
            print(f"  ℹ️  跳过了 {skip_count} 个步骤（可跳过元素未找到）")

        if close_browser:
            print(f"  浏览器将在 3 秒后关闭")
            print(f"{'='*60}")
            await asyncio.sleep(3)
        else:
            print(f"  浏览器保持打开（配置为不关闭）")
            print(f"{'='*60}")

    except Exception as e:
        print(f"\n  ❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        if close_browser:
            await asyncio.sleep(3)
        else:
            await asyncio.sleep(300)
    finally:
        if close_browser:
            await context.close()
            await p.stop()
        else:
            print("\n  配置为不关闭浏览器，等待手动关闭...")
            # 保持进程不退出，让浏览器存活
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass
            finally:
                await context.close()
                await p.stop()


# ============================================================
#  CLI 入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python run_custom_steps.py <cleaned.json> [actions_config.yaml]")
        print()
        print("示例:")
        print("  python run_custom_steps.py lingxing_elements_登录界面_cleaned.json")
        sys.exit(1)

    json_path = sys.argv[1]
    if not os.path.isfile(json_path):
        print(f"文件不存在: {json_path}")
        sys.exit(1)

    yaml_path = sys.argv[2] if len(sys.argv) > 2 else None
    if yaml_path and not os.path.isfile(yaml_path):
        print(f"动作配置不存在: {yaml_path}")
        print("将跳过动作配置，仅做定位验证")
        yaml_path = None

    asyncio.run(run(json_path, yaml_path))


if __name__ == "__main__":
    main()
