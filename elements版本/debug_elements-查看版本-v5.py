"""
领星(Lingxing) 页面元素调试工具 (终极版：Python后台直写文件 + 跨窗口继承)
用于快速定位网页元素的 selectors / XPath

用法：
  python debug_elements.py
    打开浏览器。任意跳转新窗口、新页面，甚至跨域，F1 状态和采集数据永久继承！
"""

import asyncio
import os
import sys
import argparse
import json  # 新增 json 模块用于本地写文件

from playwright.async_api import async_playwright

# ------------------------------------------------------------
#  全局共享状态 (用于跨页面、跨标签页、跨域名的状态继承)
# ------------------------------------------------------------
global_picker_state = {
    "collected": [],
    "isActive": False,
    "hoverMode": False
}


async def py_sync_state(action: str, payload=None):
    """提供给 JS 调用的 Python 后端接口，实现真正的全局状态同步与文件读写"""
    if action == "GET":
        return global_picker_state
    elif action == "ADD_COLLECTED":
        global_picker_state["collected"].append(payload)
        return len(global_picker_state["collected"])
    elif action == "CLEAR_COLLECTED":
        global_picker_state["collected"] = []
        return 0
    elif action == "SET_ACTIVE":
        global_picker_state["isActive"] = payload
        global_picker_state["hoverMode"] = False
    elif action == "SET_HOVER":
        global_picker_state["hoverMode"] = payload
        global_picker_state["isActive"] = False
    elif action == "SAVE_FILE":
        # 【核心修改】：利用 Python 直接在当前脚本所在的根目录写文件
        project_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(project_dir, 'lingxing_elements.json')

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(global_picker_state["collected"], f, ensure_ascii=False, indent=2)

        print(f"\n[写入成功] 采集数据已持久化至: {file_path}")
        return file_path


# ------------------------------------------------------------
#  注入浏览器的 JS - 元素拾取器 (与 Python 通信版)
# ------------------------------------------------------------
ELEMENT_PICKER_JS = r"""
(async () => {
    if (window.__elementPickerInstalled) return;
    window.__elementPickerInstalled = true;
    if (window !== window.top) return;

    let state = await window.pySyncState("GET");

    let isActive = state.isActive;
    let hoverMode = state.hoverMode;
    let collectedCount = state.collected.length;

    let lastHovered = null, hoverHighlight = null;
    let panel = null, fallbackBtn = null, content = null, modeLabel = null;

    function initUI() {
        if (!document.getElementById('__pickerPanel')) {
            panel = document.createElement('div');
            panel.id = '__pickerPanel';
            panel.style.cssText = `position: fixed; top: calc(50vh - 200px); left: calc(50vw - 240px); width: 480px; max-height: 80vh; background: #1e1e1e; color: #d4d4d4; font-family: 'Consolas','Courier New',monospace; font-size: 12px; border-radius: 8px; box-shadow: 0 15px 50px rgba(0,0,0,0.6); z-index: 2147483647; overflow: hidden; display: none; flex-direction: column; border: 1px solid #444;`;

            panel.innerHTML = `
                <div style="padding:8px 12px;background:#2d2d2d;border-bottom:1px solid #333;display:flex;justify-content:space-between;align-items:center;cursor:move; user-select:none;" id="__pickerHeader">
                    <span style="color:#569cd6;font-weight:bold;">🔍 元素拾取器 (后端桥接版)</span>
                    <span id="__pickerMode" style="color:#6a9955;font-size:11px;">[已暂停] 按 F1 激活</span>
                </div>
                <div id="__pickerContent" style="padding:12px;overflow-y:auto;flex:1;"></div>
                <div style="padding:6px 12px;border-top:1px solid #333;font-size:11px;color:#888;display:flex;justify-content:space-between;align-items:center;">
                    <span>F1:拾取 | F2:高亮 | ESC:关闭</span>
                    <div style="display:flex; align-items:center;">
                        <span id="__pickerCount" style="color:#dcdcaa;">全局采集: ${collectedCount}</span>
                        <span id="__pickerClearBtn" style="cursor:pointer; color:#ff6b6b; margin-left:12px; padding: 3px 8px; background: #3a3a3a; border-radius: 4px; transition: 0.2s;" title="清空所有记录">🗑️清空</span>
                    </div>
                </div>`;
            document.body.appendChild(panel);

            const clearBtn = document.getElementById('__pickerClearBtn');
            clearBtn.addEventListener('click', async function(e) {
                e.stopPropagation();
                collectedCount = await window.pySyncState("CLEAR_COLLECTED");
                document.getElementById('__pickerCount').textContent = `全局采集: ${collectedCount}`;
                const ct = document.getElementById('__pickerContent');
                if (ct) ct.innerHTML = '<div style="color:#888;text-align:center;padding:20px;">✅ 全局记录已清空</div>';
            });
            clearBtn.onmouseover = () => clearBtn.style.background = '#555';
            clearBtn.onmouseout = () => clearBtn.style.background = '#3a3a3a';

            let isDragging = false, dragOffsetX, dragOffsetY;
            const header = document.getElementById('__pickerHeader');
            header.addEventListener('mousedown', function(e) {
                isDragging = true; dragOffsetX = e.clientX - panel.offsetLeft; dragOffsetY = e.clientY - panel.offsetTop;
                document.addEventListener('mousemove', onDrag); 
                document.addEventListener('mouseup', () => { isDragging = false; document.removeEventListener('mousemove', onDrag); }, {once: true});
            });
            function onDrag(e) { 
                if (!isDragging) return; 
                panel.style.left = (e.clientX - dragOffsetX) + 'px'; panel.style.top = (e.clientY - dragOffsetY) + 'px'; 
                panel.style.right = 'auto'; panel.style.bottom = 'auto';
            }
        }

        if (!document.getElementById('__pickerFallbackBtn')) {
            fallbackBtn = document.createElement('div');
            fallbackBtn.id = '__pickerFallbackBtn';
            fallbackBtn.innerHTML = '🔍 开启拾取(F1)';
            fallbackBtn.style.cssText = `position: fixed; bottom: 30px; right: 30px; z-index: 2147483647; background: #4ec9b0; color: #1e1e1e; padding: 10px 16px; border-radius: 50px; cursor: pointer; font-weight: bold; font-family: system-ui; box-shadow: 0 4px 15px rgba(0,0,0,0.3); transition: all 0.2s; user-select: none; border: 2px solid #fff;`;
            fallbackBtn.onclick = function(e) { e.stopPropagation(); window.__pickerToggle(); };
            fallbackBtn.onmouseover = () => fallbackBtn.style.transform = 'scale(1.05)';
            fallbackBtn.onmouseout = () => fallbackBtn.style.transform = 'scale(1)';
            document.body.appendChild(fallbackBtn);
        }

        if (!document.getElementById('__pickerStyle')) {
            const style = document.createElement('style');
            style.id = '__pickerStyle';
            style.textContent = `@keyframes __pickerFlash { 0% { opacity: 1; transform: scale(1); } 100% { opacity: 0; transform: scale(1.5); } }`;
            document.head.appendChild(style);
        }

        content = document.getElementById('__pickerContent');
        modeLabel = document.getElementById('__pickerMode');

        if (isActive) { 
            panel.style.display = 'flex'; 
            if (modeLabel) { modeLabel.textContent = '[跨页激活] 持续记录中...'; modeLabel.style.color = '#4ec9b0'; }
            if (fallbackBtn) { fallbackBtn.innerHTML = '⏹️ 关 闭(ESC)'; fallbackBtn.style.background = '#ce9178'; }
        } else if (hoverMode) { 
            panel.style.display = 'flex'; 
            if (modeLabel) { modeLabel.textContent = '[高亮激活] 鼠标移动查看'; modeLabel.style.color = '#ce9178'; }
            if (fallbackBtn) { fallbackBtn.innerHTML = '⏹️ 关 闭(ESC)'; fallbackBtn.style.background = '#ce9178'; }
        }
    }

    setInterval(() => { if (document.body) initUI(); }, 1000);

    function getElementSelector(el) {
        if (el.id) return `#${CSS.escape(el.id)}`;
        const path = []; let current = el;
        while (current && current !== document.body && current !== document.documentElement) {
            let selector = current.tagName.toLowerCase();
            if (current.id) { path.unshift(`#${CSS.escape(current.id)}`); break; }
            if (current.className && typeof current.className === 'string') {
                const classes = current.className.trim().split(/\s+/).filter(c => c && !c.startsWith('el-') && c !== 'is-active' && c !== 'is-checked');
                if (classes.length > 0) selector += '.' + classes.map(c => CSS.escape(c)).join('.');
            }
            const parent = current.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(s => s.tagName === current.tagName);
                if (siblings.length > 1) selector += `:nth-child(${siblings.indexOf(current) + 1})`;
            }
            path.unshift(selector); current = current.parentElement;
        }
        return path.join(' > ');
    }

    function getXPath(el) {
        if (el.id) return `//*[@id="${el.id}"]`;
        const parts = []; let current = el;
        while (current && current !== document.body && current !== document.documentElement) {
            let idx = 0; const siblings = current.parentNode ? Array.from(current.parentNode.children).filter(s => s.tagName === current.tagName) : [];
            if (siblings.length > 1) idx = siblings.indexOf(current) + 1;
            const tag = current.tagName.toLowerCase();
            if (current.id) { parts.unshift(`//*[@id="${current.id}"]`); break; } 
            else if (idx > 0) parts.unshift(`${tag}[${idx}]`); 
            else parts.unshift(tag);
            current = current.parentNode;
        }
        return '/' + parts.join('/');
    }

    function getAllSelectors(el) {
        return {
            tag: el.tagName.toLowerCase(), id: el.id || null, class: Array.from(el.classList).join(' ') || null,
            text: (el.textContent || '').trim().substring(0, 100) || null, placeholder: el.getAttribute('placeholder') || null,
            type: el.getAttribute('type') || null, name: el.getAttribute('name') || null,
            'data-*': (() => {
                const d = {}; for (const a of el.attributes) if (a.name.startsWith('data-')) d[a.name] = a.value;
                return Object.keys(d).length ? d : null;
            })(),
            css_selector: getElementSelector(el), xpath: getXPath(el),
            playwright_selector: (() => {
                if (el.id) return `page.locator("#${CSS.escape(el.id)}")`;
                const t = (el.textContent || '').trim().substring(0, 50);
                if (t && ['button','a','span','label','div'].includes(el.tagName.toLowerCase())) return `page.getByText("${t}", { exact: true })`;
                if (el.getAttribute('placeholder')) return `page.getByPlaceholder("${el.getAttribute('placeholder')}")`;
                return getXPath(el);
            })(),
            rect: el.getBoundingClientRect(), inner_text: (el.innerText || '').trim().substring(0, 80) || null,
        };
    }

    const escapeHtml = (str) => str ? str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;') : '';

    function showElementInfo(el) {
        if (!content) return;
        const info = getAllSelectors(el);
        const lines = [
            `<div style="color:#569cd6;font-weight:bold;margin-bottom:8px;font-size:14px;">&lt;${info.tag}&gt; ${info.text ? ' - ' + escapeHtml(info.text.substring(0, 60)) : ''}</div>`,
            `<table style="width:100%;border-collapse:collapse;">`,
            ...Object.entries(info).filter(([k,v]) => v && k !== 'rect' && k !== 'inner_text').map(([k,v]) => {
                const val = typeof v === 'string' ? escapeHtml(v) : JSON.stringify(v);
                const color = k === 'playwright_selector' ? '#ce9178' : k === 'xpath' ? '#6a9955' : k === 'css_selector' ? '#dcdcaa' : '#9cdcfe';
                return `<tr><td style="padding:2px 8px 2px 0;color:#888;white-space:nowrap;vertical-align:top;">${k}</td><td style="padding:2px 0;color:${color};word-break:break-all;font-size:11px;"><code style="background:#2d2d2d;padding:1px 4px;border-radius:3px;">${val}</code></td></tr>`;
            }),
            `</table><hr style="border-color:#333;margin:8px 0;">`,
            `<div style="color:#6a9955;font-size:11px;">位置: (${Math.round(info.rect.left)}, ${Math.round(info.rect.top)}) - 大小: ${Math.round(info.rect.width)}x${Math.round(info.rect.height)}</div>`
        ];
        content.innerHTML = lines.join('\n');
    }

    function highlightElement(el) {
        if (hoverHighlight) { hoverHighlight.remove(); hoverHighlight = null; }
        const rect = el.getBoundingClientRect(); const hl = document.createElement('div'); hl.id = '__hoverHighlight';
        hl.style.cssText = `position: fixed; pointer-events: none; z-index: 2147483646; border: 2px solid #ff6b6b; background: rgba(255,107,107,0.08); border-radius: 2px; transition: all 0.1s; left: ${rect.left}px; top: ${rect.top}px; width: ${rect.width}px; height: ${rect.height}px;`;
        const tip = document.createElement('div');
        tip.style.cssText = `position: fixed; pointer-events: none; z-index: 2147483647; background: #1e1e1e; color: #d4d4d4; font-size: 11px; padding: 4px 8px; border-radius: 4px; font-family: monospace; left: ${rect.left}px; top: ${rect.bottom + 4}px; border: 1px solid #333; max-width: 400px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;`;
        const tag = el.tagName.toLowerCase(); const text = (el.textContent || '').trim().substring(0, 40);
        const selector = el.id ? `#${el.id}` : (el.className ? `.${el.className.split(' ')[0]}` : tag);
        tip.textContent = `<${tag}> ${selector} ${text ? '| ' + text : ''}`;
        hl.appendChild(tip); document.body.appendChild(hl); hoverHighlight = hl;
    }

    function onMouseMove(e) { 
        if (!hoverMode) return; 
        const el = document.elementFromPoint(e.clientX, e.clientY); 
        if (el && el !== lastHovered && el !== panel && el !== fallbackBtn && (!panel || !panel.contains(el))) { 
            lastHovered = el; highlightElement(el); 
        } 
    }

    function onClick(e) {
        if (!isActive && !hoverMode) return; 
        const el = e.target; 
        if (el === panel || (panel && panel.contains(el)) || el === fallbackBtn) return;

        showElementInfo(el);

        const item = { 
            time: new Date().toISOString(), 
            page_url: window.location.href,    
            page_title: document.title,        
            selectors: getAllSelectors(el) 
        };

        window.pySyncState("ADD_COLLECTED", item).then(total => {
            collectedCount = total;
            const countSpan = document.getElementById('__pickerCount');
            if (countSpan) countSpan.textContent = `全局采集: ${collectedCount}`;
        });

        const flash = document.createElement('div'); const rect = el.getBoundingClientRect();
        flash.style.cssText = `position: fixed; pointer-events: none; z-index: 2147483647; border: 3px solid #ff0055; border-radius: 2px; left: ${rect.left}px; top: ${rect.top}px; width: ${rect.width}px; height: ${rect.height}px; animation: __pickerFlash 0.5s ease-out;`;
        document.body.appendChild(flash); setTimeout(() => flash.remove(), 500);
    }

    window.__pickerToggle = function() {
        if (!panel) initUI();
        isActive = !isActive; hoverMode = false;

        window.pySyncState("SET_ACTIVE", isActive);

        if (isActive) { 
            document.addEventListener('click', onClick, true); 
            document.removeEventListener('mousemove', onMouseMove, true);
            if (hoverHighlight) { hoverHighlight.remove(); hoverHighlight = null; }
            if (modeLabel) { modeLabel.textContent = '[无损拾取激活] 可正常操作网页'; modeLabel.style.color = '#4ec9b0'; }
            if (panel) panel.style.display = 'flex'; 
            if (fallbackBtn) { fallbackBtn.innerHTML = '⏹️ 关 闭(ESC)'; fallbackBtn.style.background = '#ce9178'; }
        } else { 
            document.removeEventListener('click', onClick, true); 
            if (modeLabel) { modeLabel.textContent = '[已暂停] 按 F1/F2 激活'; modeLabel.style.color = '#6a9955'; }
            if (fallbackBtn) { fallbackBtn.innerHTML = '🔍 开启拾取(F1)'; fallbackBtn.style.background = '#4ec9b0'; }
        }
    };

    window.__pickerToggleHover = function() {
        if (!panel) initUI();
        hoverMode = !hoverMode; isActive = false;

        window.pySyncState("SET_HOVER", hoverMode);

        if (hoverMode) { 
            document.addEventListener('mousemove', onMouseMove, true); 
            document.addEventListener('click', onClick, true); 
            if (modeLabel) { modeLabel.textContent = '[悬停高亮激活] 鼠标移动查看'; modeLabel.style.color = '#ce9178'; }
            if (panel) panel.style.display = 'flex'; 
            if (fallbackBtn) { fallbackBtn.innerHTML = '⏹️ 关 闭(ESC)'; fallbackBtn.style.background = '#ce9178'; }
        } else { 
            document.removeEventListener('mousemove', onMouseMove, true); 
            document.removeEventListener('click', onClick, true); 
            if (hoverHighlight) { hoverHighlight.remove(); hoverHighlight = null; } lastHovered = null; 
            if (modeLabel) { modeLabel.textContent = '[已暂停] 按 F1/F2 激活'; modeLabel.style.color = '#6a9955'; }
            if (fallbackBtn) { fallbackBtn.innerHTML = '🔍 开启拾取(F1)'; fallbackBtn.style.background = '#4ec9b0'; }
        }
    };

    // 【核心修改】：彻底替换浏览器自带的下载机制
    window.__pickerExport = async function() {
        let fullState = await window.pySyncState("GET");
        let allData = fullState.collected;

        if (allData.length === 0) return alert("全局暂未采集到任何元素！");

        // 直接触发 Python 端的持久化写文件动作，并拿到真实的文件路径
        const savedPath = await window.pySyncState("SAVE_FILE");

        // 在网页端给出友好的弹窗提示
        alert(`✅ 保存成功！\n\n共导出 ${allData.length} 个元素节点\n文件已直接存入你的项目目录:\n${savedPath}`);
    };

    window.addEventListener('keydown', function(e) {
        if (e.key === 'F1') { e.preventDefault(); e.stopPropagation(); window.__pickerToggle(); } 
        else if (e.key === 'F2') { e.preventDefault(); e.stopPropagation(); window.__pickerToggleHover(); } 
        else if (e.key === 'Escape') {
            isActive = false; hoverMode = false;
            window.pySyncState("SET_ACTIVE", false);

            document.removeEventListener('click', onClick, true);
            document.removeEventListener('mousemove', onMouseMove, true);
            if (hoverHighlight) { hoverHighlight.remove(); hoverHighlight = null; }
            if (panel) panel.style.display = 'none';
            if (fallbackBtn) { fallbackBtn.innerHTML = '🔍 开启拾取(F1)'; fallbackBtn.style.background = '#4ec9b0'; }
        }
        else if (e.ctrlKey && e.key === 's') { e.preventDefault(); window.__pickerExport(); }
    }, true); 

    if (isActive) {
        document.addEventListener('click', onClick, true); 
    } else if (hoverMode) {
        document.addEventListener('mousemove', onMouseMove, true); 
        document.addEventListener('click', onClick, true); 
    }

    console.log('%c[元素拾取器] 后台写文件特权已就绪！', 'color:#4ec9b0;font-weight:bold;font-size:14px;');
})();
"""


# ------------------------------------------------------------
#  Playwright 调试脚本基础核心配置
# ------------------------------------------------------------

async def setup_context_with_picker(context):
    """为浏览器上下文统一挂载 Python 桥接函数和 JS 脚本"""
    await context.expose_function("pySyncState", py_sync_state)
    await context.add_init_script(script=ELEMENT_PICKER_JS)


# ------------------------------------------------------------
#  运行模式 (已清理过时的浏览器下载拦截器)
# ------------------------------------------------------------

async def debug_mode(url: str = None):
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
    context = await browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")

    await setup_context_with_picker(context)

    page = await context.new_page()
    page.set_default_timeout(60000)
    target_url = url or "https://ads.lingxing.com/amazon/"

    print(f"\n{'=' * 60}\n  打开页面: {target_url}\n{'=' * 60}")
    await page.goto(target_url)

    print("\n[OK] ⚡ 全局元素拾取器已就绪！(直接写入项目目录特权已开启)")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n用户终止")
    finally:
        await context.close()
        await browser.close()


async def quick_inspect():
    print(f"\n{'=' * 60}\n  领星元素调试 - 双模式启动\n{'=' * 60}")
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=False, args=["--start-maximized"],
        env={"PWDEBUG": "1"} if os.environ.get("PWDEBUG") else None,
    )
    context = await browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")

    if not os.environ.get("PWDEBUG"):
        await setup_context_with_picker(context)
        print("\n[OK] ⚡ 元素拾取器已注入！支持跨域继承、后台文件直写。")

    page = await context.new_page()
    page.set_default_timeout(60000)

    print("正在打开领星登录页面...")
    await page.goto("https://huizhixin.lingxing.com/login")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n用户终止")
    finally:
        await context.close()
        await browser.close()


async def codegen_mode():
    print(f"\n{'=' * 60}\n  启动 Playwright Codegen 录制模式\n{'=' * 60}")
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
    context = await browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")
    page = await context.new_page()
    await context.new_cdp_session(page)
    print("浏览器已打开，按 Ctrl+C 退出...\n")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await context.close()
        await browser.close()


async def test_selector(url: str, selector: str):
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=False)
    page = await browser.new_page()
    await page.goto(url)
    print(f"\n测试选择器: {selector}")
    try:
        elements = await page.query_selector_all(selector)
        print(f"匹配元素数量: {len(elements)}")
        for i, el in enumerate(elements[:5]):
            text = await el.inner_text()
            tag = await el.evaluate("el => el.tagName.toLowerCase()")
            print(f"  [{i}] <{tag}> text='{text.strip()[:60]}'")
    except Exception as e:
        print(f"选择器错误: {e}")
    input("\n按 Enter 关闭浏览器...")
    await browser.close()


def main():
    parser = argparse.ArgumentParser(description="领星页面元素调试工具")
    parser.add_argument("--url", help="指定要调试的页面URL")
    parser.add_argument("--codegen", action="store_true", help="启动录制模式")
    parser.add_argument("--test", metavar="SELECTOR", help="测试选择器")
    parser.add_argument("--quick", action="store_true", help="快捷启动")
    args = parser.parse_args()

    if len(sys.argv) == 1:
        args.quick = True

    if args.codegen:
        asyncio.run(codegen_mode())
    elif args.test:
        url = args.url or input("请输入页面URL: ") or "https://ads.lingxing.com/amazon/"
        asyncio.run(test_selector(url, args.test))
    elif args.quick:
        asyncio.run(quick_inspect())
    elif args.url:
        asyncio.run(debug_mode(args.url))
    else:
        asyncio.run(debug_mode())


if __name__ == "__main__":
    main()