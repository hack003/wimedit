# -*- coding: utf-8 -*-
"""
项目统一版本号配置 - 所有模块都从这里读取版本号。
修改版本号只需改本文件一处。
版本号格式：4 位，如 1.0.1.37（也兼容 3 位）
"""

# 程序版本号（元组形式，用于比较）
VERSION = (1, 0, 3, 27)

# 程序版本号（字符串形式，用于显示）
VERSION_STR = ".".join(str(x) for x in VERSION)

# 对外导出一个与 update.py 同名的常量，方便统一调用
APP_VERSION = VERSION_STR


if __name__ == "__main__":
    print("当前版本号：", VERSION_STR)