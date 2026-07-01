"""
帮助文档页面 — 完整功能说明
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import (
    CardWidget, TitleLabel, BodyLabel, StrongBodyLabel, ScrollArea,
)


class HelpPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("helpPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("📖 功能说明与使用指南", self))

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        content = QWidget()
        cl = QVBoxLayout(content); cl.setSpacing(12)

        sections = [
            ("一、整体架构",
             "本框架用于自动化操作领星 ERP 网页端，通过 浏览器管理 → 元素采集 → 数据清洗 → "
             "动作配置 → 编排运行 五个步骤完成自动化流程。\n\n运行入口：python main.py"),

            ("二、浏览器管理",
             "端口：18800（已统一，兼容 OpenClaw）\n\n"
             "启动方式：\n"
             "  • GUI 中点击「浏览器 → 启动浏览器」\n"
             "  • 命令行：python start_browser.py\n"
             "  • 编排器自动检测端口 18800 复用或启动\n\n"
             "特点：\n"
             "  • 单例模式：全局只启动一个浏览器实例\n"
             "  • V12 新增：Pyppeteer CDP 辅通道已启用\n"
             "  • OCR 路径支持 vars.yaml 配置"),

            ("三、元素采集（V11）",
             "使用 debug_elements-V11.py 连接已有浏览器，通过快捷键采集元素。\n\n"
             "F1 — 激活拾取模式\nF2 — 高亮模式\nF3 — 设置步骤名\n"
             "F4 — 退出工具（浏览器保持运行）\nCtrl+S — 保存\n\n"
             "V11 特性：保存时自动清洗，输出两份文件：\n"
             "  • docs/json/raw.json（原始数据）\n"
             "  • docs/cleaned/xxx_cleaned.json（清洗后）"),

            ("四、数据清洗",
             "selector_cleaner.py 生成多策略定位信息。\n\n"
             "清洗规则：\n"
             "  • 过滤动态 ID（el-id-数字、el-popper-container 等）\n"
             "  • 过滤动态 class\n"
             "  • 保留稳定 class（el-button、yy-table 等）\n"
             "  • 提取祖先锚点\n"
             "  • 标记可靠性 high/medium/low"),

            ("五、动作配置",
             "可视化编辑器 yaml_editor.html（推荐），支持：\n"
             "  • 📂 模块 — 配置元素动作参数\n"
             "  • 🔤 变量 — 编辑 vars.yaml\n"
             "  • 📋 流程 — 编排 flow.yaml\n\n"
             "动作参数：type/on_not_found/wait_before/wait_after/"
             "wait_strategy/wait_for_element/value/clear_first/click_first\n\n"
             "不配置时自动推断：input→fill, button→click, select→select"),

            ("六、变量配置（vars.yaml）",
             "在动作 YAML 中用 ${变量名} 引用。\n\n"
             "V12 新增：TESSERACT_PATH 变量可配置 OCR 路径。"),

            ("七、流程编排",
             "flow.yaml 结构：name + modules（含 json/yaml 路径）\n\n"
             "条件跳转：\n"
             "  on_success / on_failure → goto / skip_next / abort / retry_once\n\n"
             "前置流程：pre_flows 引用其他 flow.yaml\n\n"
             "运行：python orchestrator.py flow_xxx.yaml"),

            ("八、运行与交互",
             "模块成功 → 10 秒无操作自动继续\n"
             "模块失败 → 交互菜单：r(重试)/a(全部重来)/h(人工)/n(热替换)/i(插入)/s(跳过)/q(终止)"),

            ("九、元素定位策略（11 级）",
             "1. anchored 锚定\n2. text 文本匹配\n3. placeholder\n"
             "4. aria_label\n5. title\n6. name\n7. id（精确+前缀回退）\n"
             "8. css\n9. xpath\n10. CDP 深度搜索\n11. OCR 识别（Tesseract 兜底）\n\n"
             "V12：OCR 路径可配置，Pyppeteer CDP 辅通道已启用"),

            ("十、推荐工作流",
             "▸ 日常使用：python main.py\n\n"
             "▸ 完整流程：\n"
             "  1. GUI「浏览器」→ 启动\n"
             "  2. GUI「采集」→ F1 拾取 → F4 保存\n"
             "  3. GUI「清洗」→ 选择清洗\n"
             "  4. GUI「配置」→ 可视化编辑器\n"
             "  5. GUI「编排」→ 运行\n\n"
             "▸ 快速测试：python module_runner.py docs/cleaned/xxx_cleaned.json\n"
             "▸ 运行流程：python orchestrator.py docs/flows/flow_xxx.yaml"),

            ("十一、常见问题",
             "Q: 找不到浏览器？\nA: 先启动 start_browser.py 或 GUI 中启动。\n\n"
             "Q: 元素定位不到？\nA: 检查页面 URL、弹窗遮挡，重新采集+清洗。\n\n"
             "Q: 输入框填不进去？\nA: 设置 click_first: true。\n\n"
             "Q: 流程中断？\nA: 保持浏览器打开，用 n 热替换或 i 插入步骤。"),
        ]

        for title, text in sections:
            card = CardWidget(self)
            vl = QVBoxLayout(card)
            vl.addWidget(StrongBodyLabel(title))
            vl.addWidget(BodyLabel(text))
            cl.addWidget(card)

        cl.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
