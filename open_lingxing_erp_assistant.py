"""
领星ERP助手 - 打开并启用扩展 + 截图循环
在指定店铺浏览器中打开 chrome://extensions/，搜索并启用领星ERP助手，
然后导航到扩展页，再通过 DrissionPage 截图循环。

用法（作为模块导入）:
    from open_lingxing_erp_assistant import open_lingxing_erp_assistant
    open_lingxing_erp_assistant(invoke, store_id, store_name, step_log)
"""

import time
import os
import subprocess
import json
import threading
from DrissionPage import ChromiumPage, ChromiumOptions


def open_lingxing_erp_assistant(invoke, store_id, store_name, step_log):
    """
    打开并启用领星ERP助手扩展，然后启动DrissionPage截图循环。

    Args:
        invoke: 紫鸟助理调用函数 invoke(tool, args) -> dict
        store_id: 店铺 ID
        store_name: 店铺名称（用于匹配窗口和截图文件名）
        step_log: 日志回调函数 (step, status, detail)
    """

    # ---- Step 6a: 进入扩展管理页面，通过 Shadow DOM 搜索并启用领星ERP助手 ----
    step_log("进入扩展管理页面", "pending")
    try:
        invoke("visit_page", {
            "storeId": store_id,
            "url": "chrome://extensions/",
            "waitUntil": "domcontentloaded",
            "timeoutMs": 15000,
        })
        time.sleep(3)

        # 在搜索框输入"领星ERP助手"
        script_search = '''
(() => {
    let toolbar = document.querySelector('extensions-manager').shadowRoot
        .querySelector('extensions-toolbar').shadowRoot;
    let searchInput = toolbar.querySelector('#search input');
    if (!searchInput) return 'SEARCH_NOT_FOUND';
    searchInput.focus();
    searchInput.value = '领星ERP助手';
    searchInput.dispatchEvent(new Event('input', {bubbles: true}));
    return 'SEARCHED';
})()
'''
        r = invoke("execute_script", {"storeId": store_id, "script": script_search})
        raw = r.get("data", {}).get("data", {}).get("result", {})
        search_result = raw.get("value") if isinstance(raw, dict) else str(raw)
        step_log("搜索扩展管理", "pending", str(search_result))
        time.sleep(2)
    except Exception as e:
        step_log("扩展管理页面", "warn", str(e))

    # ---- Step 6b: 通过 Shadow DOM 找到领星ERP助手的开关并启用 ----
    step_log("查找并启用领星ERP助手", "pending")
    try:
        script_toggle = '''
(() => {
    let list = document.querySelector('extensions-manager').shadowRoot
        .querySelector('extensions-item-list').shadowRoot;
    let items = list.querySelectorAll('extensions-item');
    let result = '';
    items.forEach(item => {
        let s = item.shadowRoot;
        let name = (s.querySelector('#name')?.textContent || '').trim();
        if (name === '领星ERP助手') {
            let toggle = s.querySelector('#enableToggle');
            if (!toggle) { result = 'NO_TOGGLE'; return; }
            let label = toggle.getAttribute('aria-label');
            if (label === '关闭') {
                toggle.click();
                result = 'CLICKED_CLOSE_TO_OPEN';
            } else {
                result = 'LABEL_IS_' + label;
            }
        }
    });
    return result || 'NOT_FOUND';
})()
'''
        r = invoke("execute_script", {"storeId": store_id, "script": script_toggle})
        raw = r.get("data", {}).get("data", {}).get("result", {})
        toggle_result = raw.get("value") if isinstance(raw, dict) else str(raw)
        step_log("切换扩展开关", "ok", str(toggle_result))
        time.sleep(2)
    except Exception as e:
        step_log("查找领星ERP助手", "warn", str(e))

    # ---- Step 6c: 打开领星ERP助手扩展页 ----
    step_log("打开领星ERP助手页面", "pending")
    try:
        invoke("visit_page", {
            "storeId": store_id,
            "url": "chrome-extension://ohndmfaecddmecehfdidjhncfdajjeed/popup.html",
            "waitUntil": "domcontentloaded",
            "timeoutMs": 15000,
        })
        time.sleep(5)
        step_log("打开领星ERP助手页面", "ok")
    except Exception as e:
        step_log("打开领星ERP助手", "warn", str(e))

    # ---- Step 7: 使用 DrissionPage 截取扩展页截图 ----
    step_log("启动 DrissionPage 截图", "pending")
    screenshot_dir = os.path.join(os.path.dirname(__file__), "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    try:
        # 7a: 获取 ziniaobrowser 进程的 MainWindowTitle 和调试端口
        ps_cmd = (
            "Get-Process -Name ziniaobrowser | "
            "Where-Object {$_.MainWindowHandle -ne 0} | "
            "Select-Object Id, MainWindowTitle, "
            "@{Name='Port'; Expression={ (Get-NetTCPConnection -OwningProcess $_.Id -State Listen -ErrorAction SilentlyContinue).LocalPort -join ',' }} | "
            "ConvertTo-Json"
        )
        ps_result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True
        )
        stdout_text = ps_result.stdout.decode("gbk", errors="replace") if ps_result.stdout else ""
        proc_list = json.loads(stdout_text or "[]")
        if isinstance(proc_list, dict):
            proc_list = [proc_list]

        matched_port = None
        for proc in proc_list:
            title = proc.get("MainWindowTitle", "") or ""
            if title == store_name:
                ports_str = proc.get("Port", "") or ""
                # 取第一个端口
                ports = [p.strip() for p in ports_str.split(",") if p.strip().isdigit()]
                if ports:
                    matched_port = int(ports[0])
                break

        if not matched_port:
            step_log("查找调试端口", "warn", f"未找到店铺 '{store_name}' 对应的调试端口")
        else:
            step_log("查找调试端口", "ok", f"port={matched_port}")

            co = ChromiumOptions()
            co.set_local_port(matched_port)
            page = ChromiumPage(addr_or_opts=co)

            # 7b: 定位到扩展页标签
            ext_id = "ohndmfaecddmecehfdidjhncfdajjeed"
            tab = page.get_tab(url=f"chrome-extension://{ext_id}/popup.html")

            # ---- 7c: 领星独立账号登录（调用独立模块） ----
            from temu_lingxing_independ_login import try_independ_login
            try_independ_login(tab, step_log)

            # 7d: 异步循环截图，每30秒一次，最多40次
            def _screenshot_loop(tab, screenshot_dir, store_name):
                date_str = time.strftime("%Y%m%d", time.localtime())
                screenshot_path = os.path.join(screenshot_dir, "{0}_{1}.png".format(store_name, date_str))
                for i in range(40):
                    try:
                        tab.get_screenshot(path=screenshot_path)
                        step_log("扩展页截图", "ok", f"[{i+1}/40] 已保存: {screenshot_path}")
                    except Exception as e:
                        step_log("扩展页截图", "fail", str(e))
                    if i < 39:
                        time.sleep(30)

            screenshot_thread = threading.Thread(target=_screenshot_loop, args=(tab, screenshot_dir, store_name), daemon=False)
            screenshot_thread.start()
            step_log("扩展页截图", "ok", "已在后台启动截图线程")

    except Exception as e:
        step_log("DrissionPage 截图", "fail", str(e))
