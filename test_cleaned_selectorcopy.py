"""
测试清洗后的选择器是否可用
用法：python test_cleaned_selector.py lingxing_elements_登录界面_1.json
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from core.selector import robust_locate


async def test_elements(json_path: str):
    # 1. 加载清洗后的 JSON
    with open(json_path, 'r', encoding='utf-8') as f:
        elements = json.load(f)

    print(f"\n{'='*60}")
    print(f"  测试文件: {json_path}")
    print(f"  元素数量: {len(elements)}")
    print(f"{'='*60}")

    # 统计
    high = sum(1 for e in elements if e.get("cleaned", {}).get("reliability") == "high")
    medium = sum(1 for e in elements if e.get("cleaned", {}).get("reliability") == "medium")
    low = sum(1 for e in elements if e.get("cleaned", {}).get("reliability") == "low")
    anchored = sum(1 for e in elements if any(
        s.get("type") == "anchored" for s in e.get("cleaned", {}).get("strategies", [])
    ))
    print(f"  高可靠: {high} | 中可靠: {medium} | 低可靠: {low} | 含锚定: {anchored}")

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

    success_count = 0
    fail_count = 0

    try:
        current_url = None

        for i, item in enumerate(elements):
            step_name = item.get("step_name", f"步骤{i+1}")
            page_url = item.get("page_url", "")
            strategies = item.get("cleaned", {}).get("strategies", [])
            reliability = item.get("cleaned", {}).get("reliability", "unknown")
            best = item.get("cleaned", {}).get("best_strategy", {})
            selectors = item.get("selectors", {})
            tag = selectors.get("tag", "")
            text = selectors.get("text", "")
            placeholder = selectors.get("placeholder", "")

            # URL 变化时导航
            if page_url and page_url != current_url:
                print(f"\n  → 导航到: {page_url}")
                await page.goto(page_url)
                await asyncio.sleep(3)
                current_url = page_url

            print(f"\n  [{i+1}/{len(elements)}] 步骤: {step_name}")
            print(f"      标签: <{tag}> | 文本: {(text or '')[:50]} | placeholder: {placeholder or '无'}")
            print(f"      可靠性: {reliability} | 策略数: {len(strategies)}")
            print(f"      最佳: {best.get('description', best.get('type', ''))[:80]}")

            # 尝试定位
            loc = await robust_locate(page, strategies)
            if loc:
                print(f"      ✅ 定位成功！")
                try:
                    await loc.highlight()
                    await asyncio.sleep(0.3)
                except:
                    pass
                success_count += 1
            else:
                print(f"      ❌ 所有策略均失败！")
                fail_count += 1
                # 打印前 3 条失败策略
                for j, s in enumerate(strategies[:3]):
                    print(f"         策略{j+1}: {s.get('description', s.get('type', ''))[:100]}")

        print(f"\n{'='*60}")
        print(f"  测试完成！")
        print(f"  成功: {success_count} | 失败: {fail_count} | 成功率: {success_count}/{len(elements)}")
        print(f"  浏览器保持打开 10 秒")
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