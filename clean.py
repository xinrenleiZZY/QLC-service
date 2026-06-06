import re
from typing import List, Tuple, Optional

# 策略格式: (策略类型, 参数1, 参数2)  
# 比如 ("text", "提交")  -> page.getByText("提交")
#      ("role", "button", "提交") -> page.getByRole("button", { name: "提交" })

def generate_stable_selectors(
    element_info: dict,
    *,
    allow_id_prefixes: Optional[List[str]] = None,
    allow_class_fragments: Optional[List[str]] = None,
    max_text_length: int = 80
) -> List[Tuple[str, ...]]:
    """
    从原始元素信息中提取稳定定位策略，按推荐优先级排序。

    Args:
        element_info: 元素属性字典，应包含 tag, text/inner_text, placeholder, id, class, role, name, type, aria-label 等
        allow_id_prefixes: 允许保留的 id 前缀白名单 (如 ["yy-", "app-"]，业务固定 id)
        allow_class_fragments: 允许保留的 class 片段 (如 ["tree__item", "add-btn"]，有语义的定制类)
        max_text_length: 文本最大长度，超过此长度不生成精确文本定位

    Returns:
        策略列表，每个元素为元组，首项为策略类型。
        常用类型: text, role, placeholder, css, id, attribute
    """
    if allow_id_prefixes is None:
        allow_id_prefixes = []  # 不信任任何 id，除非明确加白
    if allow_class_fragments is None:
        allow_class_fragments = ["tree__item", "add-btn", "icon-", "batch-operation", "el-button"]

    strategies = []

    # ---- 1. 提取原始字段 ----
    tag = (element_info.get("tag") or "").lower()
    text = (
        element_info.get("text") or
        element_info.get("inner_text") or
        ""
    ).strip().replace("\n", " ")  # 多行文本合并
    # 去掉多余空格
    text = re.sub(r'\s+', ' ', text)

    placeholder = (element_info.get("placeholder") or "").strip()
    role = (element_info.get("role") or "").lower()
    name_attr = (element_info.get("name") or "").strip()
    type_attr = (element_info.get("type") or "").lower()
    aria_label = (element_info.get("aria-label") or element_info.get("aria_label") or "").strip()
    raw_id = (element_info.get("id") or "").strip()
    raw_class = (element_info.get("class") or "").strip()
    title = (element_info.get("title") or "").strip()

    # ---- 2. 判断 ID 是否稳定 ----
    stable_id = None
    if raw_id:
        # 动态 ID 常见特征：包含随机串、纯数字、Vue/React 生成格式
        is_dynamic = False
        # 包含 "el-id-" 或 ":" (Vue scoped)
        if "el-id-" in raw_id or ":" in raw_id:
            is_dynamic = True
        # 纯数字
        if raw_id.isdigit():
            is_dynamic = True
        # UUID 格式
        if re.match(r'^[0-9a-f]{8}-', raw_id):
            is_dynamic = True
        # 如果不在白名单里，也倾向认为动态（但可被白名单覆盖）
        if allow_id_prefixes:
            if not any(raw_id.startswith(prefix) for prefix in allow_id_prefixes):
                is_dynamic = True
        if not is_dynamic:
            stable_id = raw_id

    # ---- 3. 构建稳定的 class 选择器 ----
    stable_class_selector = None
    if raw_class:
        classes = raw_class.split()
        # 过滤掉明显为前端框架自动生成的哈希类名
        meaningful = [
            c for c in classes
            if not c.startswith("data-v-")        # Vue scoped
            and not c.startswith("css-")          # CSS Modules 常见哈希前缀
            and not re.match(r'^[a-z]+-[a-f0-9]{4,}$', c)  # 如 sc-xxxxx (styled-components)
            and not re.match(r'^_[a-zA-Z0-9]{6,}$', c)     # 常见哈希缩写
            and c in allow_class_fragments  # 严格模式：必须在白名单里
            # 如果希望更宽松，可以注释掉上一行，改用长度/模式判断
        ]
        if meaningful:
            stable_class_selector = "." + ".".join(meaningful)

    # ---- 4. 按优先级添加策略 ----
    # 4.1 用户可见文本（最稳定，只要产品不改文案就不会变）
    if text and len(text) <= max_text_length:
        strategies.append(("text", text))

    # 4.2 aria-label（前端通常写死，不受打包影响）
    if aria_label:
        strategies.append(("attribute", "aria-label", aria_label))

    # 4.3 placeholder（输入框专属，极少变动）
    if placeholder:
        strategies.append(("placeholder", placeholder))

    # 4.4 title 属性
    if title:
        strategies.append(("attribute", "title", title))

    # 4.5 表单 name 属性
    if name_attr:
        strategies.append(("attribute", "name", name_attr))

    # 4.6 角色 + 可访问名称（强烈推荐）
    if role and text:
        strategies.append(("role", role, text))
    elif role and aria_label:
        strategies.append(("role", role, aria_label))
    elif role and title:
        strategies.append(("role", role, title))
    elif role:
        # 仅有角色，没有名称，容易匹配多个，降低优先级
        strategies.append(("role", role))

    # 4.7 稳定 ID（如果存在）
    if stable_id:
        strategies.append(("id", stable_id))

    # 4.8 语义化 class 组合（需要业务方保证不会乱改）
    if stable_class_selector:
        # 进一步限定作用域：如果是特定标签，可加上标签名提高精确度
        if tag:
            strategies.append(("css", f"{tag}{stable_class_selector}"))
        strategies.append(("css", stable_class_selector))

    # 4.9 type 属性（如 input[type="submit"]，但容易匹配多个）
    if type_attr and tag in ("input", "button"):
        strategies.append(("css", f'{tag}[type="{type_attr}"]'))

    return strategies