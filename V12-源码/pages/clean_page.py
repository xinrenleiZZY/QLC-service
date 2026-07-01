"""
数据清洗页面
"""
import os
import subprocess

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    CardWidget, TitleLabel, BodyLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, ComboBox, InfoBar, QTextEdit,
)
from .utils import QProcessRunner, list_all_raw_files, DOCS_DIR, PROJECT_ROOT


class CleanPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cleanPage")
        self._browsed_file_map = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("🧹 数据清洗", self))

        cfg = CardWidget(self)
        cl = QVBoxLayout(cfg)
        r1 = QHBoxLayout()
        r1.addWidget(BodyLabel("原始 JSON 文件:", self))
        self.cb_raw = ComboBox(self)
        self.cb_raw.setMinimumWidth(350)
        self.refresh_raw_list()
        r1.addWidget(self.cb_raw)
        self.btn_browse_raw = PushButton("📂 浏览...", self)
        r1.addWidget(self.btn_browse_raw); r1.addStretch()
        cl.addLayout(r1)

        r2 = QHBoxLayout()
        self.btn_clean = PrimaryPushButton("▶️ 开始清洗", self)
        self.btn_clean.setMinimumWidth(160)
        r2.addWidget(self.btn_clean)
        r2.addWidget(BodyLabel("输出 → docs/cleaned/", self))
        r2.addStretch()
        cl.addLayout(r2)
        layout.addWidget(cfg)

        batch_card = CardWidget(self)
        bl = QVBoxLayout(batch_card)
        bl.addWidget(StrongBodyLabel("批量清洗所有文件"))
        self.btn_batch_clean = PrimaryPushButton("🧹 清洗全部原始 JSON", self)
        bl.addWidget(self.btn_batch_clean)
        layout.addWidget(batch_card)

        log_card = CardWidget(self)
        ll = QVBoxLayout(log_card); ll.setSpacing(8)
        ll.addWidget(StrongBodyLabel("清洗日志"))
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(300)
        self.log_output.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:12px;")
        ll.addWidget(self.log_output)
        layout.addWidget(log_card, 1)

        self.runner = QProcessRunner(self)
        self.runner.process.finished.connect(lambda ec, es: self.btn_clean.setEnabled(True))
        self.btn_clean.clicked.connect(self.start_clean)
        self.btn_batch_clean.clicked.connect(self.start_batch_clean)
        self.btn_browse_raw.clicked.connect(self.browse_raw_file)

    def refresh_raw_list(self):
        self.cb_raw.clear()
        files = list_all_raw_files()
        if files:
            for f in files: self.cb_raw.addItem(f)
        else:
            self.cb_raw.addItem("(无原始文件)")

    def browse_raw_file(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择原始 JSON", DOCS_DIR, "JSON Files (*.json)")
        if path:
            fname = os.path.basename(path)
            self._browsed_file_map[fname] = path
            idx = self.cb_raw.findText(fname)
            if idx >= 0: self.cb_raw.setCurrentIndex(idx)
            else:
                self.cb_raw.addItem(fname)
                self.cb_raw.setCurrentIndex(self.cb_raw.count() - 1)

    def start_clean(self):
        fname = self.cb_raw.currentText()
        if not fname or fname == "(无原始文件)":
            InfoBar.warning("请选择文件", "先选择要清洗的原始 JSON 文件", parent=self); return
        actual = self._browsed_file_map.get(fname)
        if not actual:
            for c in [os.path.join(DOCS_DIR, "json", fname), os.path.join(PROJECT_ROOT, fname)]:
                if os.path.isfile(c): actual = c; break
        if not actual:
            InfoBar.error("文件不存在", f"找不到: {fname}", parent=self); return
        self.log_output.clear()
        self.log_output.append(f"清洗: {actual}\n{'─'*50}")
        self.btn_clean.setEnabled(False)
        self.runner.run("python", ["selector_cleaner.py", actual], output_widget=self.log_output)

    def start_batch_clean(self):
        files = list_all_raw_files()
        if not files:
            InfoBar.warning("没有文件", "docs/json/ 下没有原始文件", parent=self); return
        self.log_output.clear()
        self.log_output.append(f"批量清洗 {len(files)} 个文件...\n{'─'*50}")
        self.btn_batch_clean.setEnabled(False)
        for fname in files:
            fp = os.path.join(DOCS_DIR, "json", fname)
            if os.path.isfile(fp):
                self.log_output.append(f"\n▶ {fname}")
                r = subprocess.run(["python", "selector_cleaner.py", fp],
                                   capture_output=True, text=False, cwd=PROJECT_ROOT)
                for line in r.stdout.decode('utf-8', errors='replace').split('\n'):
                    if line.strip(): self.log_output.append(f"  {line}")
                if r.stderr:
                    self.log_output.append(f"  错误: {r.stderr.decode('utf-8', errors='replace')}")
        self.log_output.append(f"\n{'─'*50}\n批量清洗完成")
        self.btn_batch_clean.setEnabled(True)
        InfoBar.success("批量清洗完成", f"已处理 {len(files)} 个文件", parent=self)
