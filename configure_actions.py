"""
configure_actions.py - 交互式配置执行动作
===========================================

用法:
    python configure_actions.py <cleaned.json>

流程:
    1. 读取清洗后的 JSON，列出每个元素
    2. 对每个元素交互式配置操作类型和参数
    3. 生成 actions_config_*.yaml 和 run_custom_steps.py

生成的 YAML 配合 run_custom_steps.py 使用。
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime


# ============================================================
#  智能推荐
# ============================================================

def _guess_var_name(placeholder: str, text: str, name_attr: str, tag: str) -> str:
    """根据元素属性猜变量名"""
    ph = (placeholder or "").lower()
    tx = (text or "").lower()
    na = (name_attr or "").lower()
    combined = f"{ph} {tx} {na}"

    if tag in ("input", "textarea"):
        if any(k in combined for k in ["密码", "password", "pwd"]):
            return "${PASSWORD}"
        if any(k in combined for k in ["账号", "用户", "邮箱", "手机",
                                        "account", "user", "email", "phone"]):
            return "${ACCOUNT}"
        if any(k in combined for k in ["搜索", "关键词", "search", "keyword"]):
            return "${SEARCH_KEYWORD}"
        if any(k in ph for k in ["请输入", "输入"]):
            return "${INPUT_VALUE}"
        return "${INPUT_VALUE}"
    return ""


def _suggest_action(tag: str) -> str:
    tag = (tag or "").lower()
    if tag in ("input", "textarea"):
        return "fill"
    elif tag in ("button", "a", "select"):
        return "click"
    # div / span / li / td 等块级 → 默认 click
    return "click"


def _suggest_wait_strategy(text: str, tag: str) -> str:
    tx = (text or "").lower()
    trigger_words = ["登录", "提交", "确认", "保存", "下一步",
                     "搜索", "查询", "login", "submit", "save", "next", "search"]
    if any(k in tx for k in trigger_words):
        return "navigation"
    return "timeout"


# ============================================================
#  YAML 生成（纯字符串拼接，无外部依赖）
# ============================================================

def _gen_yaml(actions_list: list, page_url: str, source_file: str) -> str:
    lines = [
        "# ============================================================",
        "# 动作配置文件  —  由 configure_actions.py 自动生成",
        f"# 来源: {source_file}",
        f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "# ============================================================",
        "",
    ]
    if page_url:
        lines.append(f'page_url: "{page_url}"')
    lines.append("actions:")

    for item in actions_list:
        a = item["action"]
        idx = item["index"]
        step = item.get("step_name", f"步骤{idx+1}")

        lines.append("")
        lines.append(f"  - index: {idx}")
        lines.append(f'    step_name: "{step}"')
        lines.append(f"    action:")
        lines.append(f'      type: {a["type"]}')

        if a["type"] == "fill":
            lines.append(f'      value: "{a["value"]}"')
            lines.append(f'      clear_first: {str(a.get("clear_first", True)).lower()}')

        lines.append(f'      wait_before: {a.get("wait_before", 0.5)}')
        lines.append(f'      wait_after: {a.get("wait_after", 0.5)}')
        lines.append(f'      wait_strategy: {a.get("wait_strategy", "timeout")}')

    return "\n".join(lines)


# ============================================================
#  交互式输入
# ============================================================

def _ask(prompt: str, default: str = "") -> str:
    """带默认值的交互输入"""
    if default:
        full = f"  {prompt} [{default}]: "
    else:
        full = f"  {prompt}: "
    val = input(full).strip()
    return val if val else default


# ============================================================
#  Main
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("用法: python configure_actions.py <cleaned.json>")
        print("示例: python configure_actions.py lingxing_elements_登录界面_cleaned.json")
        sys.exit(1)

    json_path = sys.argv[1]
    if not os.path.isfile(json_path):
        print(f"文件不存在: {json_path}")
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8') as f:
        elements = json.load(f)

    if not elements:
        print("JSON 文件为空！")
        sys.exit(1)

    stem = Path(json_path).stem.replace("_cleaned", "")
    page_url = elements[0].get("page_url", "")

    # ── 横幅 ──
    print()
    print("╔" + "═" * 58 + "╗")
    print(f"║  配置工具  —  {Path(json_path).name}")
    print(f"║  元素数量: {len(elements)}")
    print(f"║  页面 URL: {page_url}")
    print("╚" + "═" * 58 + "╝")
    print()

    actions_list = []

    for i, item in enumerate(elements):
        step_name = item.get("step_name", f"步骤{i+1}")
        sel = item.get("selectors", {})
        tag = sel.get("tag", "")
        text = sel.get("text", "")
        placeholder = sel.get("placeholder", "")
        name_attr = sel.get("name", "")

        default_action = _suggest_action(tag)
        default_var = _guess_var_name(placeholder, text, name_attr, tag)

        # ── 元素信息 ──
        print(f"  ┌─ [{i+1}/{len(elements)}] 步骤: {step_name}")
        print(f"  │  标签: <{tag}>  |  文本: {(text or '—')[:50]}")
        print(f"  │  placeholder: {placeholder or '—'}")
        if name_attr:
            print(f"  │  name: {name_attr}")
        print(f"  │  [推荐] 操作: {default_action}  |  变量: {default_var or '—'}")
        print(f"  ├─ 配置 ↓")

        # ── 操作类型 ──
        action_type = _ask("操作类型 (click/fill/wait_visible/hover/select/skip)", default_action)
        if action_type == "skip":
            print(f"  │  — 跳过此元素\n")
            continue

        action = {"type": action_type}

        # ── fill 特有 ──
        if action_type == "fill":
            action["value"] = _ask("填写值/变量 (例如 ${ACCOUNT} 或 固定文本)", default_var or "${INPUT_VALUE}")
            clear = _ask("填前清空? (y/n)", "y")
            action["clear_first"] = clear.lower() in ("y", "yes", "true")

        # ── 通用定时参数 ──
        action["wait_before"] = float(_ask("操作前等待 (秒)", "0.5"))

        if action_type == "click":
            default_ws = _suggest_wait_strategy(text, tag)
            action["wait_strategy"] = _ask("点击后等待策略 (timeout/navigation/element_appear)", default_ws)
            if action["wait_strategy"] == "timeout":
                action["wait_after"] = float(_ask("点击后等待 (秒)", "2.0"))
            else:
                default_after = 3.0 if action["wait_strategy"] == "navigation" else 5.0
                action["wait_after"] = float(_ask(f"点击后额外等待 (秒)", str(default_after)))
        elif action_type == "fill":
            action["wait_strategy"] = "timeout"
            action["wait_after"] = float(_ask("填写后等待 (秒)", "0.5"))
        elif action_type == "wait_visible":
            action["wait_strategy"] = "element_appear"
            action["wait_after"] = float(_ask("出现后等待 (秒)", "0.5"))
        else:
            action["wait_strategy"] = "timeout"
            action["wait_after"] = float(_ask("操作后等待 (秒)", "1.0"))

        actions_list.append({
            "index": i,
            "step_name": step_name,
            "action": action,
        })

        print(f"  │  ✅ 已配置: {action['type']}"
              f"{' = ' + action.get('value', '') if action.get('value') else ''}"
              f"  |  后等待: {action['wait_after']}s"
              f"  |  策略: {action['wait_strategy']}")
        print()

    # ── 生成文件 ──
    if not actions_list:
        print("没有配置任何动作，不生成文件。")
        return

    # 生成 YAML
    yaml_content = _gen_yaml(actions_list, page_url, Path(json_path).name)
    yaml_name = f"actions_config_{stem}.yaml"
    yaml_path = os.path.join(os.path.dirname(json_path) or ".", yaml_name)
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)

    print(f"  ✅ 生成: {yaml_path}")

    # 告诉用户用哪个命令执行
    json_name = Path(json_path).name
    print()
    print("  ────────────────────────────────────────────")
    print(f"  执行命令:")
    print(f"    python run_custom_steps.py {json_name} {yaml_name}")
    print("  ────────────────────────────────────────────")
    print()


if __name__ == "__main__":
    main()
