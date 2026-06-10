import asyncio
from session import BrowserSession

async def main():
    session = await BrowserSession.create()
    print(f"浏览器已启动，CDP: http://127.0.0.1:9222")
    print("按 Ctrl+C 关闭...")
    try:
        await asyncio.sleep(36000)  # 保持打开
    except KeyboardInterrupt:
        await session.close()

if __name__ == "__main__":
    asyncio.run(main())