"""
动作配置页面
"""
import os
import webbrowser
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from qfluentwidgets import (
    CardWidget, TitleLabel, BodyLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, ComboBox, InfoBar,
)
from .utils import list_all_cleaned_files, list_yaml_files, file_size_str, DOCS_DIR, PROJECT_ROOT


class ConfigurePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("configurePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("⚙️ 动作配置", self))

        card1 = CardWidget(self)
        c1l = QVBoxLayout(card1)
        c1l.addWidget(StrongBodyLabel("📝 可视化编辑器（推荐）"))
        c1l.addWidget(BodyLabel("打开浏览器端的 YAML 编辑器，可视化配置每个元素的操作类型和参数。"))
        self.btn_open_editor = PrimaryPushButton("📝 打开可视化编辑器", self)
        self.btn_open_editor.clicked.connect(self.open_editor)
        c1l.addWidget(self.btn_open_editor)
        layout.addWidget(card1)

        card2 = CardWidget(self)
        c2l = QVBoxLayout(card2)
        c2l.addWidget(StrongBodyLabel("💻 命令行配置"))
        c2l.addWidget(BodyLabel("选择清洗后的 JSON 文件，用 CLI 逐一配置每个元素。"))
        row = QHBoxLayout()
        self.cb_cleaned = ComboBox(self)
        self.cb_cleaned.setMinimumWidth(350)
        self.refresh_cleaned_list()
        row.addWidget(self.cb_cleaned)
        self.btn_configure_cli = PrimaryPushButton("▶️ 开始配置", self)
        self.btn_configure_cli.clicked.connect(self.start_cli_configure)
        row.addWidget(self.btn_configure_cli); row.addStretch()
        c2l.addLayout(row)
        layout.addWidget(card2)

        card3 = CardWidget(self)
        c3l = QVBoxLayout(card3)
        c3l.addWidget(StrongBodyLabel("📂 查看已生成的配置"))
        self.refresh_yaml_btn = PushButton("🔄 刷新列表", self)
        self.refresh_yaml_btn.clicked.connect(self.refresh_yaml_table)
        c3l.addWidget(self.refresh_yaml_btn)
        self.yaml_table = QTableWidget(self)
        self.yaml_table.setColumnCount(3)
        self.yaml_table.setHorizontalHeaderLabels(["文件名", "大小", "修改时间"])
        self.yaml_table.horizontalHeader().setStretchLastSection(True)
        self.yaml_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.yaml_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.yaml_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.yaml_table.setMaximumHeight(200)
        self.refresh_yaml_table()
        c3l.addWidget(self.yaml_table)
        layout.addWidget(card3)
        layout.addStretch()

    def refresh_cleaned_list(self):
        self.cb_cleaned.clear()
        files = list_all_cleaned_files()
        if files:
            for f in files: self.cb_cleaned.addItem(f)
        else:
            self.cb_cleaned.addItem("(无清洗文件)")

    def refresh_yaml_table(self):
        self.yaml_table.setRowCount(0)
        yaml_dir = os.path.join(DOCS_DIR, "yaml")
        for fname in list_yaml_files(yaml_dir):
            fp = os.path.join(yaml_dir, fname)
            r = self.yaml_table.rowCount()
            self.yaml_table.insertRow(r)
            self.yaml_table.setItem(r, 0, QTableWidgetItem(fname))
            self.yaml_table.setItem(r, 1, QTableWidgetItem(file_size_str(fp)))
            mtime = datetime.fromtimestamp(os.path.getmtime(fp))
            self.yaml_table.setItem(r, 2, QTableWidgetItem(mtime.strftime("%Y-%m-%d %H:%M")))

    def open_editor(self):
        html_path = os.path.join(PROJECT_ROOT, "yaml_editor.html")
        if os.path.isfile(html_path):
            webbrowser.open(f"file://{html_path}")
            InfoBar.info("已打开编辑器", "在浏览器中操作", parent=self)
        else:
            InfoBar.error("文件不存在", "yaml_editor.html 未找到", parent=self)

    def start_cli_configure(self):
        fname = self.cb_cleaned.currentText()
        if not fname or fname == "(无清洗文件)":
            InfoBar.warning("请选择文件", "先选择要配置的清洗后 JSON", parent=self); return
        cleaned_dir = os.path.join(DOCS_DIR, "cleaned", fname)
        if not os.path.isfile(cleaned_dir):
            InfoBar.error("文件不存在", f"找不到: {cleaned_dir}", parent=self); return
        InfoBar.info("启动配置", f"在终端运行:\npython configure_actions.py \"{cleaned_dir}\"",
                     duration=8000, parent=self)
