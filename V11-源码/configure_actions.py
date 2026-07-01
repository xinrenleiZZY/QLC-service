"""
configure_actions.py - 交互式配置执行动作 v3（全中文）
====================================================

用法:
    python configure_actions.py <cleaned.json>

功能:
    1. 读取清洗后的 JSON，列出每个元素
    2. 对每个元素交互式配置:
       - 操作类型 + 中文说明
       - 找不到时行为（跳过/终止）
       - 等待元素出现
       - 填写值、定时参数
    3. 最后询问是否执行完关闭浏览器
    4. 生成 actions_config_*.yaml

生成的 YAML 配合 run_custom_steps.py 使用。
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime


# ============================================================
#  操作类型定义（中文映射）
# ============================================================

OPERATIONS = {
    "click":         {"label": "点击",        "desc": "点击该元素（按钮、链接等）"},
    "fill":          {"label": "填写",        "desc": "在输入框中填写文字"},
    "check_exists":  {"label": "检测存在",     "desc": "检测元素是否存在，不操作，只报告结果"},
    "check_visible": {"label": "检测可见",     "desc": "检测元素是否可见，不操作，只报告结果"},
    "wait_visible":  {"label": "等待出现",     "desc": "等待元素出现在页面上后再继续"},
    "hover":         {"label": "悬浮",        "desc": "鼠标悬浮到该元素上"},
    "select":        {"label": "选择下拉",    "desc": "选择下拉框的某个选项"},
    "scroll_to":     {"label": "滚动到此",    "desc": "滚动页面直到该元素可见"},
    "screenshot":    {"label": "截图区域",    "desc": "对该元素区域截图保存"},
    "skip":          {"label": "跳过",        "desc": "不处理此元素"},
}

# 不需要额外输入的操作类型
SIMPLE_OPS = {"check_exists", "check_visible", "scroll_to", "screenshot", "wait_visible", "hover"}

# 操作对应的默认找不到行为
NOT_FOUND_DEFAULTS = {
    "check_exists":  "skip",
    "check_visible": "skip",
    "scroll_to":     "skip",
    "screenshot":    "skip",
}


# ============================================================
#  智能推荐
# ============================================================

def _guess_var_name(placeholder: str, text: str, name_attr: str, tag: str) -> str:
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
    return "click"


def _suggest_wait_strategy(text: str, tag: str) -> str:
    tx = (text or "").lower()
    trigger_words = ["登录", "提交", "确认", "保存", "下一步",
                     "搜索", "查询", "login", "submit", "save", "next", "search"]
    if any(k in tx for k in trigger_words):
        return "navigation"
    return "timeout"


def _suggest_not_found(text: str, tag: str, op_type: str) -> str:
    """智能推荐"找不到时行为" """
    # 检测类操作默认跳过
    if op_type in NOT_FOUND_DEFAULTS:
        return NOT_FOUND_DEFAULTS[op_type]

    tx = (text or "").lower()
    dangerous = ["删除", "注销", "关闭", "取消订单"]
    if any(k in tx for k in dangerous):
        return "skip"
    if tag in ("input", "textarea"):
        return "skip"
    if any(k in tx for k in ["登录", "提交", "确认", "保存"]):
        return "fail"
    return "fail"


# ============================================================
#  交互式输入工具
# ============================================================

def _ask(prompt: str, default: str = "") -> str:
    if default:
        full = f"  {prompt} [{default}]: "
    else:
        full = f"  {prompt}: "
    val = input(full).strip()
    return val if val else default


def _ask_yn(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"  {prompt} ({hint}): ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes", "true", "1")


def _select_op(question: str, default: str) -> str:
    """交互式选择操作类型"""
    print(f"  {question}")
    ops_list = [k for k in OPERATIONS if k != "skip"]
    for idx, (key, info) in enumerate(OPERATIONS.items()):
        if key == "skip":
            continue
        marker = " ← 推荐" if key == default else ""
        print(f"    {idx+1}. {info['label']} — {info['desc']}{marker}")
    print(f"    s. 跳过 — 不处理此元素")
    print(f"    q. 退出配置")

    while True:
        val = input(f"  请输入编号或操作名 [{default}]: ").strip().lower()
        if not val:
            return default
        if val == "q":
            print("\n  用户退出配置。")
            sys.exit(0)
        if val == "s":
            return "skip"
        # 按编号
        if val.isdigit():
            idx = int(val) - 1
            ops_keys = [k for k in OPERATIONS if k != "skip"]
            if 0 <= idx < len(ops_keys):
                return ops_keys[idx]
        # 按操作名
        if val in OPERATIONS:
            return val
        print(f"  输入无效，请重新输入。")


# ============================================================
#  YAML 生成
# ============================================================

def _gen_yaml(actions_list: list, page_url: str, source_file: str,
              close_browser: bool = True) -> str:
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
    lines.append(f'close_browser: {str(close_browser).lower()}')
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
        lines.append(f'      on_not_found: {a.get("on_not_found", "fail")}')

        # 等待元素出现
        if a.get("wait_for_element", False):
            wait_timeout = a.get("wait_timeout", 10)
            lines.append(f"      wait_for_element: true")
            lines.append(f"      wait_timeout: {wait_timeout}")
        else:
            lines.append(f"      wait_for_element: false")

        # fill 特有
        if a["type"] == "fill":
            lines.append(f'      value: "{a["value"]}"')
            lines.append(f'      clear_first: {str(a.get("clear_first", True)).lower()}')

        # 截图类可以指定文件名
        if a["type"] == "screenshot":
            lines.append(f'      screenshot_name: "{a.get("screenshot_name", f"step_{idx}")}"')

        # 定时参数（检测类操作可以没有等待策略）
        if a["type"] not in ("check_exists", "check_visible"):
            lines.append(f'      wait_before: {a.get("wait_before", 0.5)}')
            lines.append(f'      wait_after: {a.get("wait_after", 0.5)}')
            lines.append(f'      wait_strategy: {a.get("wait_strategy", "timeout")}')

    return "\n".join(lines)


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
    print(f"║  动作配置工具 v3")
    print(f"║")
    print(f"║  数据文件: {Path(json_path).name}")
    print(f"║  元素数量: {len(elements)} 个")
    print(f"║  页面地址: {page_url}")
    print(f"║")
    print(f"║  提示: 每个元素你需要选择:")
    print(f"║    ① 做什么操作（点击/填写/检测存在/检测可见/等待出现等）")
    print(f"║    ② 找不到元素时是【跳过】还是【终止流程】")
    print(f"║    ③ 是否需要等它出现后再操作（动态弹窗等场景）")
    print(f"║    ④ 等待时机参数（操作前/后等多久）")
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
        default_on_not_found = _suggest_not_found(text, tag, default_action)

        # ── 元素信息（中文） ──
        print(f"  ┌─ 第 {i+1}/{len(elements)} 个元素 — 步骤: {step_name}")
        print(f"  │")
        print(f"  │  标签: <{tag}>")
        print(f"  │  文本: {(text or '（无文本）')[:60]}")
        print(f"  │  占位符: {placeholder or '（无）'}")
        if name_attr:
            print(f"  │  name属性: {name_attr}")
        print(f"  │")
        print(f"  │  推荐 | 操作: {OPERATIONS.get(default_action, {}).get('label', default_action)}"
              f"  |  变量: {default_var or '（无需填写）'}"
              f"  |  找不到时: {'终止流程' if default_on_not_found == 'fail' else '跳过继续'}")
        print(f"  ├──── 请配置这个元素 ↓")

        # ── 操作类型（中文选择） ──
        action_type = _select_op("要做什么操作？", default_action)
        if action_type == "skip":
            print(f"  │  → 已跳过此元素\n")
            continue

        op_label = OPERATIONS.get(action_type, {}).get("label", action_type)
        action = {"type": action_type}

        # ── 找不到时行为 ──
        nf_default = _suggest_not_found(text, tag, action_type)
        nf_label = "终止流程" if nf_default == "fail" else "跳过继续"
        nf_input = _ask(f"如果找不到元素怎么办？(fail=必须找到, 终止流程 / skip=可跳过, 继续执行)",
                        nf_default)
        action["on_not_found"] = nf_input

        # ── 是否等待元素出现 ──
        wait_for = _ask_yn("是否要等这个元素出现后再操作？（例如弹窗、异步加载的内容）", False)
        action["wait_for_element"] = wait_for
        if wait_for:
            action["wait_timeout"] = int(_ask("最长等多少秒？", "10"))

        # ── fill 特有：填什么 ──
        if action_type == "fill":
            action["value"] = _ask("填写什么内容？（可用 ${变量名} 引用 vars.yaml 里的变量）",
                                   default_var or "${INPUT_VALUE}")
            clear = _ask("填写前要清空已有内容吗？(y/n)", "y")
            action["clear_first"] = clear.lower() in ("y", "yes", "true")

        # ── screenshot 特有：文件名 ──
        if action_type == "screenshot":
            action["screenshot_name"] = _ask("截图文件名（不含扩展名）", f"step_{i}")

        # ── 定时参数（检测类操作不需要） ──
        if action_type not in ("check_exists", "check_visible"):
            action["wait_before"] = float(_ask("操作前先等多久？(秒)", "0.5"))

            if action_type == "click":
                default_ws = _suggest_wait_strategy(text, tag)
                ws_map = {"timeout": "固定等待", "navigation": "等页面加载", "element_appear": "等元素出现"}
                ws_hint = "/".join([f"{k}={v}" for k, v in ws_map.items()])
                action["wait_strategy"] = _ask(
                    f"点击后等待什么？({ws_hint})", default_ws)
                if action["wait_strategy"] == "timeout":
                    action["wait_after"] = float(_ask("固定等多久？(秒)", "2.0"))
                else:
                    default_after = 3.0 if action["wait_strategy"] == "navigation" else 5.0
                    action["wait_after"] = float(_ask("再额外等多久？(秒)", str(default_after)))
            elif action_type == "fill":
                action["wait_strategy"] = "timeout"
                action["wait_after"] = float(_ask("填写后等多久？(秒)", "0.5"))
            elif action_type == "wait_visible":
                action["wait_strategy"] = "element_appear"
                action["wait_after"] = float(_ask("元素出现后再等多久？(秒)", "0.5"))
            else:
                action["wait_strategy"] = "timeout"
                action["wait_after"] = float(_ask("操作完后等多久？(秒)", "1.0"))

        actions_list.append({
            "index": i,
            "step_name": step_name,
            "action": action,
        })

        # ── 配置摘要 ──
        nf_display = "终止流程" if action.get("on_not_found") == "fail" else "跳过继续"
        summary = f"  │  → 已配置: {op_label}"
        if action.get('value'):
            summary += f"  内容: {action['value']}"
        summary += f"  |  找不到: {nf_display}"
        if action.get('wait_for_element'):
            summary += f"  |  等出现: {action.get('wait_timeout')}s"
        if action_type not in ("check_exists", "check_visible"):
            summary += f"  |  后等待: {action['wait_after']}s"
        print(summary)
        print()

    # ── 全局配置 ──
    if actions_list:
        print(f"  ┌─ 全局设置")
        close_browser = _ask_yn("全部执行完后是否关闭浏览器？（选否则保持打开，方便查看结果）", True)
        print(f"  │  → 关闭浏览器: {'是' if close_browser else '否，保持打开'}")
        print()
    else:
        close_browser = True

    # ── 生成文件 ──
    if not actions_list:
        print("没有配置任何动作，不生成文件。")
        return

    yaml_content = _gen_yaml(actions_list, page_url, Path(json_path).name,
                             close_browser)
    yaml_name = f"actions_config_{stem}.yaml"
    yaml_path = os.path.join(os.path.dirname(json_path) or ".", yaml_name)
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)

    print(f"  ✅ 已生成配置文件: {yaml_path}")
    json_name = Path(json_path).name
    print()
    print("  ────────────────────────────────────────────")
    print(f"  执行命令:")
    print(f"    python run_custom_steps.py {json_name} {yaml_name}")
    print("  ────────────────────────────────────────────")
    print()


if __name__ == "__main__":
    main()
