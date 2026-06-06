# ai_code_generator.py
# 1. 读取每条元素的 cleaned.strategies
# 2. 按 step_name 分组
# 3. 按 page_url 插入导航跳转
# 4. 根据 tag 判断 click 还是 fill
# 5. 把 strategies 列表直接作为代码字符串写进去
# 6. 输出一个完整的 Python 文件