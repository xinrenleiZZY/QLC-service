"""
文件管理页面
"""
import os
from datetime import datetime

from PyQt5.QtCore import QUrl, QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from qfluentwidgets import (
    CardWidget, TitleLabel, BodyLabel,
    PrimaryPushButton, PushButton,
)
from .utils import DOCS_DIR, PROJECT_ROOT


class FilesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filesPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("📂 文件管理", self))

        dir_card = CardWidget(self)
        dl = QHBoxLayout(dir_card); dl.setSpacing(12)
        dirs = [
            ("📄 原始 JSON", "json"),
            ("✨ 清洗后", "cleaned"),
            ("⚙️ 动作配置", "yaml"),
            ("📋 流程定义", "flows"),
        ]
        for label, sub in dirs:
            btn = PushButton(label, self)
            btn.clicked.connect(lambda checked, d=sub: QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.join(DOCS_DIR, d))))
            dl.addWidget(btn)
        btn_root = PushButton("📁 项目根目录", self)
        btn_root.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(PROJECT_ROOT)))
        dl.addWidget(btn_root); dl.addStretch()
        layout.addWidget(dir_card)

        self.file_table = QTableWidget(self)
        self.file_table.setColumnCount(5)
        self.file_table.setHorizontalHeaderLabels(["文件名", "类型", "大小", "修改时间", "目录"])
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.setSortingEnabled(True)
        self.file_table.verticalHeader().setDefaultSectionSize(28)
        self.file_table.cellDoubleClicked.connect(self.on_double_click)
        layout.addWidget(self.file_table, 1)

        btn_row = QHBoxLayout()
        self.btn_refresh = PrimaryPushButton("🔄 刷新列表", self)
        self.btn_refresh.clicked.connect(self.refresh_files)
        btn_row.addWidget(self.btn_refresh); btn_row.addStretch()
        self.file_count_label = BodyLabel("", self)
        btn_row.addWidget(self.file_count_label)
        layout.addLayout(btn_row)

        self.refresh_files()

    def refresh_files(self):
        self.file_table.setRowCount(0)
        total = 0
        for dirname in ["json", "cleaned", "yaml", "flows"]:
            d = os.path.join(DOCS_DIR, dirname)
            if not os.path.isdir(d): continue
            for fname in sorted(os.listdir(d)):
                if not (fname.endswith('.json') or fname.endswith('.yaml') or fname.endswith('.yml')):
                    continue
                fp = os.path.join(d, fname)
                if not os.path.isfile(fp): continue
                total += 1
                r = self.file_table.rowCount()
                self.file_table.insertRow(r)
                self.file_table.setItem(r, 0, QTableWidgetItem(fname))
                ext = os.path.splitext(fname)[1]
                self.file_table.setItem(r, 1, QTableWidgetItem("YAML" if ext in ('.yaml','.yml') else "JSON"))
                size = os.path.getsize(fp)
                sz = f"{size}B" if size < 1024 else f"{size/1024:.1f}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
                self.file_table.setItem(r, 2, QTableWidgetItem(sz))
                self.file_table.setItem(r, 3, QTableWidgetItem(
                    datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M")))
                self.file_table.setItem(r, 4, QTableWidgetItem(dirname))
        self.file_count_label.setText(f"共 {total} 个文件")

    def on_double_click(self, row, col):
        item = self.file_table.item(row, 0)
        dir_item = self.file_table.item(row, 4)
        if item and dir_item:
            fp = os.path.join(DOCS_DIR, dir_item.text(), item.text())
            if os.path.isfile(fp):
                QDesktopServices.openUrl(QUrl.fromLocalFile(fp))
