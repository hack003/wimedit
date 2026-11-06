# -*- coding: utf-8 -*-
"""DPI 缩放工具：统一处理高分屏缩放，无需第三方库。

用法：
  from dpi_utils import px, SCALE_RATIO, enable_dpi_aware, dpi_geometry
  enable_dpi_aware()          # 在 main() 顶部调用一次
  width = px(100)              # 像素数值全部走 px()
  root.geometry(dpi_geometry(540, 470))  # 窗口尺寸
"""

import ctypes


def get_dpi_scale():
    """获取当前屏幕 DPI 缩放比例。100% = 1.0，150% = 1.5，200% = 2.0。"""
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        if hdc:
            try:
                dpi_value = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
                if dpi_value:
                    return dpi_value / 96.0
            finally:
                ctypes.windll.user32.ReleaseDC(0, hdc)
    except Exception:
        pass
    return 1.0


# DPI 感知必须在获取实际 DPI 之前调用（否则在某些系统上会拿到 96）
try:
    # 先尝试 SetProcessDpiAwarenessContext（Win10+，支持 Per-Monitor V2）
    _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    _set_ctx = getattr(ctypes.windll.user32, "SetProcessDpiAwarenessContext", None)
    if _set_ctx is not None:
        try:
            if not _set_ctx(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                # 失败回退到老 API
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    else:
        # 老系统直接用 SetProcessDPIAware
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass


# 获取缩放比例（在开启 DPI 感知之后）
SCALE_RATIO = get_dpi_scale()


def px(num):
    """像素值按 DPI 比例缩放。在 100% 缩放下保持原值。"""
    if num is None:
        return 0
    try:
        return int(num * SCALE_RATIO)
    except Exception:
        try:
            return int(num)
        except Exception:
            return 0


def fpx(num):
    """浮点版 px，用于需要小数精度的场景（Canvas 绘图坐标等）。"""
    if num is None:
        return 0.0
    try:
        return float(num) * SCALE_RATIO
    except Exception:
        try:
            return float(num)
        except Exception:
            return 0.0


def dpi_geometry(width, height, x=None, y=None):
    """生成 geometry 字符串：按 DPI 缩放宽高，可选 x/y 偏移。"""
    w = px(int(width))
    h = px(int(height))
    if x is None or y is None:
        return f"{w}x{h}"
    return f"{w}x{h}+{int(x)}+{int(y)}"


def scaled_tuple(*nums):
    """把一串数字全部按 px 缩放，返回元组。例如 padx/pady=(5, 10)。"""
    return tuple(px(n) for n in nums)


def font_scaled(family, size, *rest):
    """生成字体参数元组：(family, size, ...rest)。
    注意：字号单位是 pt（磅），操作系统会按 DPI 自动渲染，
    不应再乘以 SCALE_RATIO（会导致双重放大）。
    只有像素单位（width/height/padx/pady/rowheight 等）需要 px()。
    """
    if rest:
        return (family, int(size)) + tuple(rest)
    return (family, int(size))


def enable_dpi_aware():
    """兼容函数：本模块 import 时已开启，这里提供空实现以便入口显式调用。"""
    return True


def from_logic_px(num):
    """winfo_x / winfo_width 等拿到的逻辑像素，反向换算回原始坐标。
    当需要与「按 DPI 放大前」的坐标做比较时使用。"""
    if num is None:
        return 0
    try:
        return int(num / SCALE_RATIO) if SCALE_RATIO else int(num)
    except Exception:
        try:
            return int(num)
        except Exception:
            return 0