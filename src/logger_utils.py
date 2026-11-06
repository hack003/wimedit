# -*- coding: utf-8 -*-
"""统一日志管理模块

设计目标：
  1. 四个级别：ERROR / WARNING / INFO / DEBUG（默认 WARNING）
  2. 子模块自动跟随全局级别，由界面滑动条控制
  3. 内存缓冲所有日志，切换级别后可重刷显示

模块名约定：在代码中调用 log(模块名, 级别, 消息)，如：
  log("unmount", "ERROR", "卸载失败: xxx")
"""

import os
import sys
import threading
import datetime
from enum import IntEnum
from collections import deque


# ---------- 级别定义 ----------

class LogLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


_LEVEL_NAMES = {
    "ERROR": LogLevel.ERROR,
    "WARNING": LogLevel.WARNING,
    "INFO": LogLevel.INFO,
    "DEBUG": LogLevel.DEBUG,
}

_LEVEL_DISPLAY = {
    LogLevel.ERROR: "ERROR",
    LogLevel.WARNING: "WARN ",
    LogLevel.INFO:  "INFO ",
    LogLevel.DEBUG: "DEBUG",
}

# 有序列表（UI 展示顺序）
LEVEL_ORDER = [
    ("DEBUG",   LogLevel.DEBUG,   "#3a86ff"),  # 蓝
    ("INFO",    LogLevel.INFO,    "#2ec4b6"),  # 青
    ("WARNING", LogLevel.WARNING, "#ff9f1c"),  # 橙
    ("ERROR",   LogLevel.ERROR,   "#e71d36"),  # 红
]

# 已知模块列表（UI 展示顺序）
KNOWN_MODULES = ["mount", "unmount", "optimize", "info", "system"]


# ---------- 运行时状态 ----------

_lock = threading.Lock()

# 全局级别（默认 WARNING，可由界面滑动条调整）
_global_level = LogLevel.WARNING

# 各模块独立级别（模块名 -> LogLevel）。空则继承 global_level
_module_levels = {}

# 日志回调：UI 程序注入自己的日志显示函数，否则写入 stdout
_log_callback = None

# 仅负责把一行文本追加到 UI 文本框，不会再次写回日志缓冲
# 由 logger_utils.log 统一调用，避免双向递归
_raw_append_callback = None

# 内存缓冲区（保留所有日志，用于级别切换后重刷）
_max_buffer_size = 20000
_log_buffer = deque(maxlen=_max_buffer_size)

# 配置是否已加载（已弃用配置文件，仅保留兼容标志）
_config_loaded = True


# ---------- 对外 API ----------

def init_logger(callback=None):
    """初始化。callback: UI 提供的日志显示函数，签名 callback(message_str)。
    （已不再读取配置文件，级别由界面滑动条控制。）
    """
    global _log_callback
    with _lock:
        _log_callback = callback


def set_raw_append_callback(callback):
    """设置一个仅负责把一行文本追加到 UI 的回调。
    当设置后，logger_utils.log 的输出将调用它，而不是 _log_callback，
    从而避免与主线程的 _log 函数互相递归。
    """
    global _raw_append_callback
    with _lock:
        _raw_append_callback = callback


def set_log_level(level):
    """设置全局级别（接受 IntEnum 或字符串）"""
    global _global_level
    if isinstance(level, LogLevel):
        _global_level = level
    elif isinstance(level, str):
        lv = _LEVEL_NAMES.get(level.upper())
        if lv is not None:
            _global_level = lv


def set_module_level(module, level):
    """设置某模块的日志级别。传 level=None 清除独立设置，回退到 global_level。"""
    if level is None:
        with _lock:
            if module.lower() in _module_levels:
                del _module_levels[module.lower()]
        return
    if isinstance(level, LogLevel):
        lv = level
    elif isinstance(level, str):
        lv = _LEVEL_NAMES.get(level.upper())
        if lv is None:
            return
    else:
        return
    with _lock:
        _module_levels[module.lower()] = lv


def get_global_level():
    """取得全局当前级别"""
    return _global_level


def get_global_level_name():
    """取得全局当前级别显示名称"""
    for name, lv in _LEVEL_NAMES.items():
        if lv == _global_level:
            return name
    return "ERROR"


def get_module_level(module):
    """取得某模块的显式设置级别（未设置则返回 None）"""
    with _lock:
        return _module_levels.get(module.lower())


def get_effective_level(module):
    """取得某模块实际生效的级别"""
    with _lock:
        return _module_levels.get(module.lower(), _global_level)


def get_effective_level_name(module):
    """取得某模块实际生效的级别名称"""
    lv = get_effective_level(module)
    for name, nlv in _LEVEL_NAMES.items():
        if nlv == lv:
            return name
    return "ERROR"


def get_all_known_modules():
    """返回已知模块名列表（已在缓冲中出现过的也会被加入）"""
    extra = set()
    with _lock:
        for entry in _log_buffer:
            extra.add(entry["module"])
    merged = list(KNOWN_MODULES)
    for m in sorted(extra):
        if m not in merged:
            merged.append(m)
    return merged


def should_log(module, level):
    """判断某模块某级别的消息是否需要输出"""
    eff = get_effective_level(module)
    return level >= eff


def clear_buffer():
    """清空内存缓冲"""
    with _lock:
        _log_buffer.clear()


def get_filtered_lines(min_level=None):
    """返回所有已缓冲的、不低于 min_level 的格式化行。
    min_level 为 None 时使用当前全局/各模块级别做逐行过滤。
    """
    lines = []
    with _lock:
        entries = list(_log_buffer)
    for entry in entries:
        lv = entry["level"]
        if min_level is None:
            eff = get_effective_level(entry["module"])
            if lv < eff:
                continue
        else:
            if lv < min_level:
                continue
        lines.append(entry["text"])
    return lines


def level_from_name(name):
    """字符串 -> LogLevel，失败返回 None"""
    return _LEVEL_NAMES.get(str(name).strip().upper())


def log(module, level, message):
    """核心输出函数。module=模块名，level=级别，message=消息。
    所有消息都会写入内存缓冲，但仅当级别满足时才输出到 UI/控制台。
    """
    if not isinstance(level, LogLevel):
        lv = _LEVEL_NAMES.get(str(level).upper(), LogLevel.ERROR)
    else:
        lv = level
    try:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        tag = _LEVEL_DISPLAY.get(lv, "?")
        line = f"[{ts}] [{tag}] [{module}] {message}"
    except Exception:
        line = f"[{module}] {message}"

    # 无论是否输出，都写入内存缓冲（便于后续切换级别重刷）
    with _lock:
        _log_buffer.append({
            "ts": ts,
            "module": module.lower(),
            "level": lv,
            "text": line,
        })

    if not should_log(module, lv):
        return

    # 优先走 raw append 回调（避免与主线程 _log 函数互相递归）
    if _raw_append_callback is not None:
        try:
            _raw_append_callback(line)
            return
        except Exception:
            pass

    if _log_callback is not None:
        try:
            _log_callback(line)
        except Exception:
            pass
    else:
        try:
            print(line, flush=True)
        except Exception:
            pass


def log_direct(module, level, message, append_to_ui=True):
    """写入缓冲但不触发 logger_utils 的 callback。
    常用于被 callback 自身调用，避免双向递归。"""
    if not isinstance(level, LogLevel):
        lv = _LEVEL_NAMES.get(str(level).upper(), LogLevel.ERROR)
    else:
        lv = level
    try:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        tag = _LEVEL_DISPLAY.get(lv, "?")
        line = f"[{ts}] [{tag}] [{module}] {message}"
    except Exception:
        line = f"[{module}] {message}"

    with _lock:
        _log_buffer.append({
            "ts": ts,
            "module": module.lower(),
            "level": lv,
            "text": line,
        })

    if not append_to_ui:
        return
    if not should_log(module, lv):
        return
    if _log_callback is not None:
        try:
            _log_callback(line)
        except Exception:
            pass
    else:
        try:
            print(line, flush=True)
        except Exception:
            pass


# ---------- 便捷封装（对应三个级别）----------

def log_error(module, message):
    log(module, LogLevel.ERROR, message)


def log_warning(module, message):
    log(module, LogLevel.WARNING, message)


def log_debug(module, message):
    log(module, LogLevel.DEBUG, message)


# ---------- 兼容旧接口：给 WimEditor 的日志回调 ----------

def create_module_callback(module, level=LogLevel.DEBUG):
    """返回一个 callback(msg) 函数，供 WimEditor 的 _log 参数使用。
    
    所有通过该 callback 传入的消息都会被打上指定模块名。
    实际是否输出由该模块的当前日志级别决定。
    """
    def callback(msg):
        log(module, level, msg)
    return callback