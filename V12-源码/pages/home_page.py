"""
首页 — 工作流概览
"""
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel
)
from qfluentwidgets import (
    CardWidget, TitleLabel, CaptionLabel, BodyLabel,
    PrimaryPushButton, PushButton, StrongBodyLabel,
)
from .utils import (
    list_all_raw_files, list_all_cleaned_files,
    list_yaml_files, list_all_flow_files, DOCS_DIR,
)


class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)

        title = TitleLabel("领星 ERP 自动化框架 V12", self)
        subtitle = BodyLabel(
            "完整工作流：浏览器管理 → 元素采集 → 数据清洗 → 动作配置 → 编排运行", self)
        subtitle.setStyleSheet("color: #888; font-size: 14px;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # 快捷操作
        card = CardWidget(self)
        cl = QVBoxLayout(card); cl.setSpacing(16)
        cl.addWidget(StrongBodyLabel("快速启动", self))

        btn_grid = QGridLayout(); btn_grid.setSpacing(12)
        self.btn_browser = PrimaryPushButton("🚀 启动浏览器", self)
        self.btn_collect = PrimaryPushButton("📡 采集元素", self)
        self.btn_clean = PrimaryPushButton("🧹 清洗数据", self)
        self.btn_configure = PrimaryPushButton("⚙️ 配置动作", self)
        self.btn_flow = PrimaryPushButton("▶️ 运行流程", self)
        self.btn_editor = PushButton("📝 可视化编辑器", self)
        for b in [self.btn_browser, self.btn_collect, self.btn_clean,
                   self.btn_configure, self.btn_flow, self.btn_editor]:
            b.setMinimumHeight(48); b.setMaximumWidth(200)
        btn_grid.addWidget(self.btn_browser, 0, 0)
        btn_grid.addWidget(self.btn_collect, 0, 1)
        btn_grid.addWidget(self.btn_clean, 1, 0)
        btn_grid.addWidget(self.btn_configure, 1, 1)
        btn_grid.addWidget(self.btn_flow, 2, 0)
        btn_grid.addWidget(self.btn_editor, 2, 1)
        cl.addLayout(btn_grid)
        layout.addWidget(card)

        # 帮助
        help_card = CardWidget(self)
        hl = QHBoxLayout(help_card); hl.setSpacing(16)
        hi = TitleLabel("📖", self); hi.setStyleSheet("font-size: 32px;")
        hl.addWidget(hi)
        ht = QWidget(self)
        htl = QVBoxLayout(ht); htl.setSpacing(2)
        htl.addWidget(StrongBodyLabel("新手上路？查看完整功能说明"))
        htl.addWidget(BodyLabel("快捷键、参数详解、推荐工作流、常见问题一站式查阅"))
        hl.addWidget(ht, 1)
        self.btn_open_help = PushButton("📖 查看帮助", self)
        self.btn_open_help.setMinimumHeight(40)
        hl.addWidget(self.btn_open_help)
        layout.addWidget(help_card)

        # 统计
        stat_card = CardWidget(self)
        sl = QHBoxLayout(stat_card); sl.setSpacing(30)
        self.stat_raw = self._mk("📄", "原始 JSON", "0")
        self.stat_cleaned = self._mk("✨", "清洗后", "0")
        self.stat_yaml = self._mk("⚙️", "动作配置", "0")
        self.stat_flows = self._mk("📋", "流程定义", "0")
        sl.addWidget(self.stat_raw); sl.addWidget(self.stat_cleaned)
        sl.addWidget(self.stat_yaml); sl.addWidget(self.stat_flows)
        layout.addWidget(stat_card)
        layout.addStretch()
        self.refresh_stats()

    def _mk(self, icon, label, value):
        w = QWidget(); l = QVBoxLayout(w); l.setSpacing(4)
        v = TitleLabel(value, self); v.setObjectName("statValue")
        v.setStyleSheet("font-size: 28px;")
        l.addWidget(v)
        l.addWidget(CaptionLabel(f"{icon} {label}", self))
        return w

    def refresh_stats(self):
        self.stat_raw.findChild(TitleLabel).setText(str(len(list_all_raw_files())))
        self.stat_cleaned.findChild(TitleLabel).setText(str(len(list_all_cleaned_files())))
        self.stat_yaml.findChild(TitleLabel).setText(str(len(list_yaml_files(
            os.path.join(DOCS_DIR, "yaml")))))
        self.stat_flows.findChild(TitleLabel).setText(str(len(list_all_flow_files())))
