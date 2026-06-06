"""
测试脚本：test_cleaned_selector.py
测试清洗后的选择器是否可用
用法：python test_cleaned_selector.py lingxing_elements_登录界面_cleaned.json
"""

import asyncio
import json
import sys
import os

# 把 core 目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from core.selector import robust_locate, smart_click, smart_fill


async def test_elements(json_path: str):
    # 1. 加载清洗后的 JSON
    with open(json_path, 'r', encoding='utf-8') as f:
        elements = json.load(f)

    print(f"\n{'='*60}")
    print(f"  测试文件: {json_path}")
    print(f"  元素数量: {len(elements)}")
    print(f"{'='*60}")

    # 2. 启动浏览器
    p = await async_playwright().start()
    context = await p.chromium.launch_persistent_context(
        user_data_dir="playwright_profile",
        channel="chrome",
        headless=False,
        no_viewport=True,
        locale="zh-CN",
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
    )
    page = await context.new_page()
    page.set_default_timeout(30000)

    try:
        # 3. 导航到登录页面
        first_url = elements[0]["page_url"]
        print(f"\n  → 导航到: {first_url}")
        await page.goto(first_url)
        await asyncio.sleep(3)

        # 4. 按顺序测试每个元素
        for i, item in enumerate(elements):
            step_name = item.get("step_name", f"步骤{i+1}")
            strategies = item.get("cleaned", {}).get("strategies", [])
            reliability = item.get("cleaned", {}).get("reliability", "unknown")
            best = item.get("cleaned", {}).get("best_strategy", {})
            selectors = item.get("selectors", {})
            tag = selectors.get("tag", "")
            text = selectors.get("text", "")
            placeholder = selectors.get("placeholder", "")

            print(f"\n  [{i+1}/{len(elements)}] 步骤: {step_name}")
            print(f"      标签: <{tag}> | 文本: {text[:40] if text else '无'} | placeholder: {placeholder or '无'}")
            print(f"      可靠性: {reliability} | 策略数: {len(strategies)}")
            print(f"      最佳策略: {best.get('description', best.get('type', ''))}")

            # 5. 尝试定位
            loc = await robust_locate(page, strategies)
            if loc:
                print(f"      ✅ 定位成功！")
                
                # 6. 高亮一下（方便观察）
                try:
                    await loc.highlight()
                    await asyncio.sleep(0.5)
                except:
                    pass

                # 7. 如果是输入框，填入测试值
                if tag == "input" or tag == "textarea":
                    test_value = ""
                    if "账号" in placeholder or "用户" in placeholder or "手机" in placeholder:
                        test_value = "xiazhanggui"
                    elif "密码" in placeholder:
                        test_value = "123amazoncom"
                    else:
                        test_value = "123amazoncom"
                    
                    try:
                        await loc.fill(test_value)
                        print(f"      ✅ 填写成功: {test_value}")
                        await asyncio.sleep(0.5)
                        # 清掉（不真填）
                        await loc.fill("")
                    except Exception as e:
                        print(f"      ⚠️ 填写失败: {e}")

                # 8. 如果是按钮，不真点（只验证可定位）
                elif tag == "button":
                    print(f"      ✅ 按钮可定位（未点击）")
                else:
                    print(f"      ✅ 元素可定位")

            else:
                print(f"      ❌ 所有策略均失败！")
                # 打印失败详情
                for j, s in enumerate(strategies):
                    print(f"         策略{j+1}: {s.get('description', s.get('type', ''))}")

        print(f"\n{'='*60}")
        print(f"  测试完成！浏览器保持打开 10 秒")
        print(f"{'='*60}")
        await asyncio.sleep(10)

    except Exception as e:
        print(f"\n  ❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        await asyncio.sleep(5)
    finally:
        await context.close()
        await p.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python test_cleaned_selector.py <cleaned.json>")
        sys.exit(1)

    asyncio.run(test_elements(sys.argv[1]))