"""
module_runner.py - 单个 JSON 模块执行器
=======================================

职责:
  - 接收 session + cleaned.json + actions.yaml
  - 执行该 JSON 内的所有步骤
  - 返回 RunResult（成功/失败索引）
  - 完全独立，不依赖其他模块

用法:
    session = await BrowserSession.create()
    result = await ModuleRunner.run(session, "xxx_cleaned.json")
    print(f"成功: {result.success}, 失败: {result.fail}")
"""

import asyncio
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

try:
    import yaml as _yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from session import BrowserSession
from advanced_runner import (
    StepRunner, StepAction, StepState, RunResult,
    CDPEngine, OCREngine, EventBus,
    RetryConfig, HumanInterventionConfig
)


class ModuleRunner:
    """
    单模块执行器。
    执行一个 cleaned JSON 中所有步骤，返回结果。
    可独立运行，也可被 Orchestrator 调用。
    """

    def __init__(self, session: BrowserSession):
        self.session = session
        self.page = session.page
        self.cdp = session.cdp
        self.event_bus = session.event_bus

    async def run(self, json_path: str, yaml_path: str = None,
                  label: str = None) -> RunResult:
        """
        执行一个模块。
        json_path: cleaned JSON 文件路径
        yaml_path: 可选的动作配置 YAML
        label: 模块名称（显示用）
        """
        result = RunResult()

        # ── 1. 加载 JSON（兼容3种格式）──
        with open(json_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        # 格式A: {"metadata": ..., "elements": [...]}  → V10 原始
        if isinstance(raw, dict) and "elements" in raw:
            elements = raw["elements"]
            print(f"  ℹ️  检测到 V10 格式，已提取 elements 数组")
        # 格式B: [{metadata, elements, cleaned}, ...] → V10 清洗后（包裹体）
        elif isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], dict) and "elements" in raw[0]:
            elements = []
            for wrapper in raw:
                inner = wrapper.get("elements", [])
                for el in inner:
                    # 从 wrapper 继承 step_name
                    if "step_name" not in el or not el.get("step_name"):
                        el["step_name"] = wrapper.get("metadata", {}).get("step_name", "unknown")
                    # 从 wrapper 继承 page_url
                    if "page_url" not in el or not el.get("page_url"):
                        el["page_url"] = wrapper.get("metadata", {}).get("page_url", "")
                    # 如果元素本身没有 cleaned，但 wrapper 有 → 补进去
                    if "cleaned" not in el and "cleaned" in wrapper:
                        el["cleaned"] = wrapper["cleaned"]
                    elements.append(el)
            print(f"  ℹ️  检测到 V10 清洗格式，已展平 {len(elements)} 个元素")
        # 格式C: [{step_name, selectors, cleaned}, ...] → 传统清洗格式
        elif isinstance(raw, list):
            elements = raw
        else:
            raise ValueError(f"不支持的 JSON 格式: {type(raw)}")
        print(f"\n{'='*60}")
        print(f"  📦 模块: {label or Path(json_path).stem}")
        print(f"  元素: {len(elements)} 个")
        print(f"{'='*60}")

        result.total = len(elements)

        # ── 2. 加载 YAML ──
        actions = {}
        if yaml_path is None:
            stem = Path(json_path).stem.replace("_cleaned", "")
            candidate = os.path.join(PROJECT_ROOT, f"actions_config_{stem}.yaml")
            if os.path.isfile(candidate):
                yaml_path = candidate

        if yaml_path and HAS_YAML:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = _yaml.safe_load(f) or {}
            for item in data.get("actions", []):
                idx = item.get("index")
                if idx is not None:
                    actions[idx] = item.get("action", {})
            print(f"  动作配置: {len(actions)} 个")

        # ── 3. 加载 vars ──
        vars_dict = {}
        vars_path = os.path.join(PROJECT_ROOT, "vars.yaml")
        if os.path.isfile(vars_path) and HAS_YAML:
            with open(vars_path, 'r', encoding='utf-8') as f:
                vars_dict = {k: v for k, v in (_yaml.safe_load(f) or {}).items()
                             if isinstance(k, str)}

        # ── 4. 按 step_name 分组 ──
        groups = OrderedDict()
        for i, item in enumerate(elements):
            sn = item["step_name"]
            if sn not in groups:
                groups[sn] = []
            groups[sn].append(i)

        # ── 5. 执行 ──
        runner = StepRunner(self.page, self.cdp, self.event_bus,
                            elements, vars_dict, HumanInterventionConfig())

        has_fatal = False
        iter_success = 0
        iter_skip = 0
        iter_fail = 0
        current_url = None

        try:
            for group_idx, (step_name, indices) in enumerate(groups.items(), 1):
                if has_fatal:
                    print(f"\n  [{group_idx}/{len(groups)}] 区域: {step_name}")
                    print(f"      ⏭️  致命错误，跳过")
                    iter_skip += len(indices)
                    for gi in indices:
                        result.skip_indices.append(gi)
                    continue

                # URL 导航（从浏览器实际 URL 比对）
                first_item = elements[indices[0]]
                expected_url = first_item.get("page_url", "")
                if expected_url:
                    await self._ensure_url(expected_url)

                is_parent = "父元素" in step_name
                zone_label = "📦" if is_parent else "📍"

                print(f"\n  [{group_idx}/{len(groups)}] {zone_label} {step_name} ({len(indices)}元素)")

                for ei, global_idx in enumerate(indices, 1):
                    item = elements[global_idx]
                    strategies = item.get("cleaned", {}).get("strategies", [])
                    action = actions.get(global_idx, self._auto_action(item))

                    sel = item.get("selectors", {})
                    tag = sel.get("tag", "")
                    text = (sel.get("text", "") or "")[:25]

                    step = StepAction(global_idx, step_name, strategies, action, {})
                    ptag = " [容器内]" if runner.parent_locator is not None else ""
                    print(f"      └ [{ei}/{len(indices)}] <{tag}> {text:25s} → {action.get('type','?')}{ptag}")

                    state, msg = await runner.run(step)

                    if state == StepState.SUCCESS:
                        iter_success += 1
                        result.success_indices.append(global_idx)
                    elif state == StepState.SKIP:
                        iter_skip += 1
                        result.skip_indices.append(global_idx)
                    elif state == StepState.FAIL:
                        iter_fail += 1
                        result.fail_indices.append(global_idx)
                        if action.get("on_not_found", "fail") == "fail":
                            has_fatal = True

            result.success = iter_success
            result.skip = iter_skip
            result.fail = iter_fail
            result.fatal = has_fatal

        except Exception as e:
            print(f"  ❌ 模块异常: {e}")
            import traceback
            traceback.print_exc()

        # ── 统计 ──
        print(f"\n{'─'*40}")
        print(f"  模块执行完毕: {label or Path(json_path).stem}")
        print(f"  ✅ {result.success}  ⏭️  {result.skip}  ❌ {result.fail}")
        net = result.success + result.fail
        if net > 0:
            print(f"  有效率: {result.success}/{net} ({result.success*100//net}%)")
        print(f"{'─'*40}")

        return result

    async def _ensure_url(self, expected_url: str):
        """确保当前 URL 匹配"""
        if not expected_url:
            return
        try:
            actual = self.page.url
            if actual.rstrip("/") == expected_url.rstrip("/"):
                return
            if actual.startswith(expected_url):
                return
        except Exception:
            pass

        print(f"  → 跳转到: {expected_url}")
        await self.page.goto(expected_url, wait_until="load", timeout=20000)
        await asyncio.sleep(2)

    def _auto_action(self, item: dict) -> dict:
        """智能默认动作"""
        sel = item.get("selectors", {})
        tag = sel.get("tag", "").lower()
        text = sel.get("text", "") or ""
        step_name = item.get("step_name", "")

        if "父元素" in step_name:
            return {"type": "locate_parent", "on_not_found": "skip"}
        if "是否可见" in step_name:
            return {"type": "check_exists", "on_not_found": "skip"}
        if tag in ("input", "textarea"):
            return {"type": "fill", "value": "${INPUT_VALUE}",
                    "clear_first": True, "on_not_found": "skip"}
        if tag in ("button", "a"):
            ws = "navigation" if any(k in text for k in ["登录", "提交", "确认", "保存"]) else "timeout"
            return {"type": "click", "on_not_found": "skip", "wait_strategy": ws}
        if tag == "select":
            return {"type": "select", "value": "", "on_not_found": "skip"}
        return {"type": "click", "on_not_found": "skip"}


# ============================================================
#  独立入口（测试单个模块）
# ============================================================
async def _main():
    if len(sys.argv) < 2:
        print("用法: python module_runner.py <cleaned.json> [actions.yaml]")
        sys.exit(1)

    json_path = sys.argv[1]
    yaml_path = sys.argv[2] if len(sys.argv) > 2 else None

    session = await BrowserSession.create()
    runner = ModuleRunner(session)
    result = await runner.run(json_path, yaml_path)

    keep = input("\n浏览器保持打开？按 q 退出，回车保持: ").strip().lower()
    if keep == 'q':
        await session.close()
    else:
        print("浏览器保持打开。手动关闭或运行 session.close()")


if __name__ == "__main__":
    asyncio.run(_main())
