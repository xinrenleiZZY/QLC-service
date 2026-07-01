"""
编排运行页面
"""
import os
import webbrowser

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
)
from qfluentwidgets import (
    CardWidget, TitleLabel, BodyLabel, StrongBodyLabel,
    PrimaryPushButton, PushButton, ComboBox, LineEdit, CheckBox,
    InfoBar, QTextEdit,
)
from .utils import QProcessRunner, list_all_flow_files, list_yaml_files, DOCS_DIR, PROJECT_ROOT


class OrchestratePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("orchestratePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("▶️ 编排运行", self))

        cfg = CardWidget(self)
        cl = QVBoxLayout(cfg); cl.setSpacing(12)
        r1 = QHBoxLayout()
        r1.addWidget(BodyLabel("选择流程文件:", self))
        self.cb_flows = ComboBox(self)
        self.cb_flows.setMinimumWidth(400)
        self.refresh_flow_list()
        r1.addWidget(self.cb_flows)
        self.btn_browse_flow = PushButton("📂 浏览...", self)
        self.btn_browse_flow.clicked.connect(self.browse_flow)
        r1.addWidget(self.btn_browse_flow); r1.addStretch()
        cl.addLayout(r1)

        r2 = QHBoxLayout()
        self.btn_run = PrimaryPushButton("▶️ 运行流程", self)
        self.btn_run.setMinimumWidth(160)
        r2.addWidget(self.btn_run)
        self.btn_stop_flow = PushButton("⏹ 停止", self)
        self.btn_stop_flow.setEnabled(False)
        r2.addWidget(self.btn_stop_flow); r2.addSpacing(20)
        self.cb_close_browser = CheckBox("运行后关闭浏览器", self)
        r2.addWidget(self.cb_close_browser); r2.addStretch()
        cl.addLayout(r2)
        layout.addWidget(cfg)

        create_card = CardWidget(self)
        crl = QVBoxLayout(create_card)
        crl.addWidget(StrongBodyLabel("快速创建流程"))
        c_row = QHBoxLayout()
        self.flow_name_input = LineEdit(self)
        self.flow_name_input.setPlaceholderText("输入流程名称...")
        self.flow_name_input.setText("新建流程")
        c_row.addWidget(self.flow_name_input)
        self.btn_create_flow = PrimaryPushButton("📋 创建空白流程", self)
        self.btn_create_flow.clicked.connect(self.create_flow)
        c_row.addWidget(self.btn_create_flow); c_row.addStretch()
        crl.addLayout(c_row)

        # 可视化编排流程按钮
        c_row2 = QHBoxLayout()
        self.btn_flow_editor = PrimaryPushButton("📝 可视化编排流程", self)
        self.btn_flow_editor.clicked.connect(self.open_flow_editor)
        c_row2.addWidget(self.btn_flow_editor)
        c_row2.addWidget(BodyLabel("打开浏览器的流程编排编辑器（yaml_editor.html → 📋 标签页）"))
        c_row2.addStretch()
        crl.addLayout(c_row2)
        layout.addWidget(create_card)

        log_card = CardWidget(self)
        ll = QVBoxLayout(log_card); ll.setSpacing(8)
        ll.addWidget(StrongBodyLabel("运行日志"))
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:12px;")
        ll.addWidget(self.log_output)
        layout.addWidget(log_card, 1)

        self.runner = QProcessRunner(self)
        self.runner.process.finished.connect(self._on_flow_finished)
        self.btn_run.clicked.connect(self.run_flow)
        self.btn_stop_flow.clicked.connect(self.stop_flow)

    def refresh_flow_list(self):
        self.cb_flows.clear()
        files = list_all_flow_files()
        root_files = [f for f in list_yaml_files(PROJECT_ROOT) if f.startswith("flow_")]
        all_f = sorted(set(files + root_files))
        if all_f:
            for f in all_f: self.cb_flows.addItem(f)
        else:
            self.cb_flows.addItem("(无流程文件)")

    def browse_flow(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择流程文件", PROJECT_ROOT, "YAML Files (*.yaml *.yml)")
        if path:
            fname = os.path.basename(path)
            idx = self.cb_flows.findText(fname)
            if idx >= 0: self.cb_flows.setCurrentIndex(idx)
            else:
                self.cb_flows.addItem(fname)
                self.cb_flows.setCurrentIndex(self.cb_flows.count() - 1)

    def create_flow(self):
        name = self.flow_name_input.text().strip()
        if not name:
            InfoBar.warning("输入名称", "请输入流程名称", parent=self); return
        yaml_name = f"flow_{name}.yaml"
        yaml_path = os.path.join(DOCS_DIR, "flows", yaml_name)
        if os.path.isfile(yaml_path):
            InfoBar.warning("已存在", f"{yaml_name} 已存在", parent=self); return
        content = f"""name: {name}

# pre_flows:
#   - flow_检查登录态.yaml

modules:
  - name: 模块名
    json: 模块名_cleaned.json
    # yaml: actions_config_模块名.yaml
"""
        with open(yaml_path, 'w', encoding='utf-8') as f: f.write(content)
        self.refresh_flow_list()
        InfoBar.success("已创建", f"{yaml_name} 已保存到 docs/flows/", parent=self)

    def run_flow(self):
        fname = self.cb_flows.currentText()
        if not fname or fname == "(无流程文件)":
            InfoBar.warning("请选择流程", "先选择一个流程文件", parent=self); return
        actual = None
        for c in [os.path.join(DOCS_DIR, "flows", fname), os.path.join(PROJECT_ROOT, fname)]:
            if os.path.isfile(c): actual = c; break
        if not actual:
            InfoBar.error("文件不存在", f"找不到: {fname}", parent=self); return
        self.log_output.clear()
        self.log_output.append(f"▶ 运行流程: {fname}\n  文件: {actual}\n{'─'*50}\n")
        self.btn_run.setEnabled(False)
        self.btn_stop_flow.setEnabled(True)
        self.runner.run("python", ["orchestrator.py", actual], output_widget=self.log_output)

    def stop_flow(self):
        self.runner.stop()
        self.btn_run.setEnabled(True)
        self.btn_stop_flow.setEnabled(False)
        self.log_output.append("\n⏹ 已手动停止")

    def open_flow_editor(self):
        html_path = os.path.join(PROJECT_ROOT, "yaml_editor.html")
        if os.path.isfile(html_path):
            webbrowser.open(f"file://{html_path}")
            InfoBar.info("已打开流程编辑器", "切换到「📋 流程」标签页编排", parent=self)
        else:
            InfoBar.error("文件不存在", "yaml_editor.html 未找到", parent=self)

    def _on_flow_finished(self, exit_code, exit_status):
        self.btn_run.setEnabled(True)
        self.btn_stop_flow.setEnabled(False)
        self.log_output.append(f"\n{'✅' if exit_code == 0 else '⚠️'} 流程退出码: {exit_code}")
