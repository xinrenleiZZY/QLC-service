"""
selector_cleaner.py
元素选择器清洗模块 - 独立于采集工具，可随时更新规则重新清洗
用法:
    python selector_cleaner.py element_raw.json           # 输出 element_cleaned.json
    python selector_cleaner.py element_raw.json --inplace  # 在原文件上添加 cleaned 字段
"""

import json
import re
import sys
import os
from typing import List, Dict, Any, Optional


# ============================================================
#  配置区：修改规则只需要改这里
# ============================================================

STABLE_CLASS_FRAGMENTS = [
    "tree__item", "add-btn", "el-button", "el-textarea__inner",
    "el-checkbox__inner", "el-dialog", "el-overlay",
    "icon-tianjia", "icon-sousuo", "icon-xiaotubiao-xiala",
    "batch-operation", "yy-layout-content", "yy-table",
    "single-select-down",
]

DYNAMIC_ID_PATTERNS = [
    r'^el-id-\d+',
    r':',
    r'^\d+$',
    r'^[0-9a-f]{8}-',
    r'random',
    r'^rc-',
]

DYNAMIC_CLASS_PATTERNS = [
    r'^data-v-',
    r'^css-[a-z0-9]+$',
    r'^sc-[a-zA-Z]+$',
    r'^_[a-zA-Z0-9]{5,}$',
]

LAYOUT_CLASSES = {
    "show-box", "show", "hide", "hidden", "visible",
    "left", "right", "top", "bottom", "center",
    "flex", "grid", "block", "inline",
    "justify-between", "justify-center", "justify-end",
    "items-center", "items-start", "items-end",
    "ml-auto", "mr-auto", "mx-auto",
    "pt-8", "pb-8", "pl-8", "pr-8", "mt-8", "mb-8",
}

STATE_CLASSES = {
    "is-active", "is-focus", "is-checked", "is-disabled",
    "is-expanded", "is-current", "is-focusable", "is-required",
}

TEST_ATTRIBUTES = [
    "data-testid", "data-test-id", "data-cy", "data-test", "data-qa"
]

TRACKING_ATTRIBUTES = [
    "data-sensors-click", "data-track", "data-track-id"
]


# ============================================================
#  核心清洗逻辑
# ============================================================

def is_dynamic_id(id_str: str) -> bool:
    for pattern in DYNAMIC_ID_PATTERNS:
        if re.search(pattern, id_str, re.IGNORECASE):
            return True
    return False


def is_dynamic_class(class_str: str) -> bool:
    for pattern in DYNAMIC_CLASS_PATTERNS:
        if re.search(pattern, class_str):
            return True
    if class_str in LAYOUT_CLASSES or class_str in STATE_CLASSES:
        return True
    return False


def filter_stable_classes(raw_class: str) -> List[str]:
    if not raw_class:
        return []
    classes = raw_class.split()
    stable = []
    for c in classes:
        if c in STABLE_CLASS_FRAGMENTS:
            stable.append(c)
        elif any(frag in c for frag in STABLE_CLASS_FRAGMENTS if frag.endswith('-')):
            stable.append(c)
        elif not is_dynamic_class(c) and len(c) > 2:
            stable.append(c)
    return stable


def build_self_strategies(info: dict, data_attrs: dict, stable_id: str, 
                          stable_classes: List[str], tag: str, text: str,
                          placeholder: str, aria_label: str, title: str,
                          name_attr: str, type_attr: str, role: str) -> List[dict]:
    """
    构建目标元素自身的定位策略（不含锚定）。
    抽成单独函数，方便被锚定逻辑复用。
    """
    strategies = []

    # 最高优先级：测试属性
    for attr_name in TEST_ATTRIBUTES:
        if attr_name in data_attrs and data_attrs[attr_name]:
            strategies.append({"type": "attribute", "value": f'[{attr_name}="{data_attrs[attr_name]}"]'})

    # 第二优先级：用户可见文本
    if text and len(text) <= 80:
        strategies.append({"type": "text", "value": text})

    # 第三优先级：aria-label
    if aria_label:
        strategies.append({"type": "aria_label", "value": aria_label})

    # 第四优先级：placeholder
    if placeholder:
        strategies.append({"type": "placeholder", "value": placeholder})

    # 第五优先级：埋点属性
    for attr_name in TRACKING_ATTRIBUTES:
        if attr_name in data_attrs and data_attrs[attr_name]:
            strategies.append({"type": "attribute", "value": f'[{attr_name}="{data_attrs[attr_name]}"]'})

    # 第六优先级：title
    if title:
        strategies.append({"type": "title", "value": title})

    # 第七优先级：name 属性
    if name_attr:
        strategies.append({"type": "name", "value": name_attr})

    # 第八优先级：role + 名称
    if role and text:
        strategies.append({"type": "role", "value": f'{role}[name="{text}"]'})

    # 第九优先级：稳定 ID
    if stable_id:
        strategies.append({"type": "id", "value": stable_id})

    # 第十优先级：稳定 class
    if stable_classes and tag:
        strategies.append({"type": "css", "value": f'{tag}.{".".join(stable_classes[:3])}'})

    # 兜底：type 属性
    if type_attr and tag in ("input", "button"):
        strategies.append({"type": "css", "value": f'{tag}[type="{type_attr}"]'})

    return strategies


def build_anchor_strategies(ancestors: list, self_strategies: List[dict]) -> List[dict]:
    """
    利用祖先信息，为自身策略生成"父元素锚定"版本。
    锚定策略排在最前面。
    """
    anchor_strategies = []

    for ancestor in ancestors:
        anchor_type = None
        anchor_value = None

        # 判断这个祖先能用来做什么类型的锚点
        if ancestor.get("role") in ["dialog", "alertdialog"]:
            anchor_type = "role"
            anchor_value = ancestor["role"]
        elif ancestor.get("aria_label"):
            anchor_type = "aria_label"
            anchor_value = ancestor["aria_label"]
        elif ancestor.get("id") and not is_dynamic_id(ancestor["id"]):
            anchor_type = "id"
            anchor_value = ancestor["id"]
        elif ancestor.get("class") and "el-dialog" in ancestor["class"]:
            anchor_type = "css"
            anchor_value = ".el-dialog"
        else:
            continue  # 这个祖先不可用于锚定

        # 为前 3 个自身策略生成锚定版本
        for s in self_strategies[:3]:
            if s["type"] in ["id"]:
                continue  # id 本身就唯一，不需要锚定

            anchor_strategies.append({
                "type": "anchored",
                "anchor": {"type": anchor_type, "value": anchor_value},
                "target": s,
                "description": f'{anchor_type}={anchor_value} 内 {s["type"]}={s.get("value", "")}'
            })

    return anchor_strategies


def clean_element(raw: dict) -> dict:
    """
    清洗单条元素信息，返回:
    {
        "strategies": [...],          # 按优先级排序的策略列表（含锚定）
        "best_strategy": {...},       # 最佳策略
        "reliability": "high/medium/low",
        "filtered_out": {...},        # 被过滤掉的信息
        "anchors_available": [...]    # 可用的祖先锚点
    }
    """
    info = raw.get("selectors", raw)
    ancestors = raw.get("ancestors", [])

    tag = (info.get("tag") or "").lower()
    text = (info.get("text") or info.get("inner_text") or "").strip()
    text = re.sub(r'\s+', ' ', text.replace("\n", " "))
    placeholder = (info.get("placeholder") or "").strip()
    aria_label = (info.get("aria-label") or "").strip()
    title = (info.get("title") or "").strip()
    name_attr = (info.get("name") or "").strip()
    type_attr = (info.get("type") or "").lower()
    role = (info.get("role") or "").lower()
    raw_id = (info.get("id") or "").strip()
    raw_class = (info.get("class") or "").strip()

    # data-* 属性
    data_attrs = info.get("data-*") or {}
    if not isinstance(data_attrs, dict):
        data_attrs = {}

    filtered_out = {"id": None, "classes": []}

    # ---- 过滤 ID ----
    stable_id = None
    if raw_id and not is_dynamic_id(raw_id):
        stable_id = raw_id
    if raw_id and is_dynamic_id(raw_id):
        filtered_out["id"] = raw_id

    # ---- 过滤 class ----
    stable_classes = filter_stable_classes(raw_class)
    if raw_class:
        all_classes = raw_class.split()
        filtered_out["classes"] = [c for c in all_classes if c not in stable_classes]

    # ---- 构建自身策略 ----
    self_strategies = build_self_strategies(
        info, data_attrs, stable_id, stable_classes,
        tag, text, placeholder, aria_label, title,
        name_attr, type_attr, role
    )

    # ---- 【核心】筛选可用的稳定祖先 ----
    stable_ancestors = []
    for a in ancestors:
        anchor_id = (a.get("id") or "").strip()
        anchor_role = (a.get("role") or "").strip()
        anchor_aria = (a.get("aria_label") or "").strip()
        anchor_class = (a.get("class") or "").strip()
        is_stable = a.get("is_stable_anchor", False)

        if is_stable or anchor_id or anchor_role or anchor_aria or ("el-dialog" in anchor_class):
            stable_ancestors.append({
                "tag": a.get("tag", ""),
                "id": anchor_id,
                "role": anchor_role,
                "aria_label": anchor_aria,
                "class": anchor_class,
                "depth": a.get("depth", 0)
            })

    # ---- 【核心】生成锚定策略 ----
    anchor_strategies = build_anchor_strategies(stable_ancestors, self_strategies)

    # ---- 合并策略：锚定策略优先 ----
    final_strategies = anchor_strategies + self_strategies

    # ---- 判断可靠性 ----
    has_test_attr = any(
        s.get("type") == "attribute" and "testid" in s.get("value", "").lower()
        for s in final_strategies
    )
    if has_test_attr:
        reliability = "high"
    elif anchor_strategies:
        reliability = "high"
    elif self_strategies and self_strategies[0]["type"] in ["text", "aria_label", "placeholder"]:
        reliability = "high"
    elif stable_id or stable_classes:
        reliability = "medium"
    else:
        reliability = "low"

    best_strategy = final_strategies[0] if final_strategies else None

    return {
        "strategies": final_strategies,
        "best_strategy": best_strategy,
        "reliability": reliability,
        "filtered_out": filtered_out,
        "anchors_available": [
            f'{a.get("role") or a.get("id") or a.get("tag")}' 
            for a in stable_ancestors
        ]
    }


# ============================================================
#  批量清洗入口
# ============================================================

def clean_file(input_path: str, output_path: str = None, inplace: bool = False):
    """清洗整个 JSON 文件"""
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    for item in data:
        item["cleaned"] = clean_element(item)

    if inplace:
        output_path = input_path
    elif output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_cleaned{ext}"

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 统计
    high = sum(1 for d in data if d.get("cleaned", {}).get("reliability") == "high")
    medium = sum(1 for d in data if d.get("cleaned", {}).get("reliability") == "medium")
    low = sum(1 for d in data if d.get("cleaned", {}).get("reliability") == "low")
    anchored = sum(1 for d in data if any(
        s.get("type") == "anchored" for s in d.get("cleaned", {}).get("strategies", [])
    ))

    print(f"\n✅ 清洗完成: {output_path}")
    print(f"   总数: {len(data)} | 高可靠: {high} | 中可靠: {medium} | 低可靠: {low}")
    print(f"   含锚定策略: {anchored} 条")
    return output_path


# ============================================================
#  命令行入口
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python selector_cleaner.py <element_raw.json> [--inplace]")
        sys.exit(1)

    input_file = sys.argv[1]
    inplace_flag = "--inplace" in sys.argv

    clean_file(input_file, inplace=inplace_flag)
# # 基础版已有的
# "el-id-" in raw_id          # Element UI
# ":" in raw_id               # Vue scoped
# raw_id.isdigit()            # 纯数字
# re.match(r'^[0-9a-f]{8}-')  # UUID

# # 完整版新增的
# "random" in raw_id.lower()  # Ant Design 随机 ID
# "rc-" in raw_id.lower()     # Ant Design rc- 前缀