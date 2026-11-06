# -*- coding: utf-8 -*-
"""
映像编辑辅助工具 - 主入口
功能：镜像编辑、引导管理、启动测试
"""

import os
import sys
import tkinter as tk
import threading
from tkinter import ttk, messagebox
from datetime import datetime

_src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from dpi_utils import px, SCALE_RATIO, dpi_geometry, font_scaled, scaled_tuple

from wim_editor import WimEditor
from boot_manager import BootManager
from boot_test import BootTest
from app_version import VERSION_STR as APP_VERSION
import logger_utils
try:
    from update import UpdateChecker
    _HAS_UPDATE_MODULE = True
except Exception:
    _HAS_UPDATE_MODULE = False
    UpdateChecker = None


class WIMTool:
    def __init__(self, root):
        self.root = root
        self.root.title(f"映像编辑辅助工具 v{APP_VERSION}")
        self.root.geometry(dpi_geometry(540, 470))
        self.root.minsize(px(540), px(470))
        self.root.resizable(True, True)

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(self.base_dir, "data")
        self.wimlib_exe = os.path.join(self.data_dir, "Wimlib", "wimlib-imagex.exe")
        self.dism_exe = os.path.join(self.data_dir, "DISM", "dism.exe")
        self.sevenz_exe = os.path.join(self.data_dir, "7Z", "7z.exe")

        # 自动更新检查器
        self.update_checker = None
        if _HAS_UPDATE_MODULE and UpdateChecker is not None:
            try:
                self.update_checker = UpdateChecker(
                    root=self.root,
                    log_callback=self._log,
                    status_callback=self._set_status,
                    progress_callback=self._set_progress,
                    toast_callback=self._toast,
                )
            except Exception:
                self.update_checker = None

        self._set_icon(self.root)

        self._build_ui()
        self._init_modules()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=px(4))
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        main.rowconfigure(1, weight=0)

        self.switch_frame = ttk.Frame(main)
        self.switch_frame.grid(row=0, column=0, sticky="nsew")

        self.content_frame = ttk.Frame(self.switch_frame)
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        self.tab_control = ttk.Notebook(self.content_frame)
        self.tab_control.pack(fill=tk.BOTH, expand=True)

        # 配置 ttk Treeview 全局样式：DPI 缩放的字体和行高（紧凑版，避免占满屏幕）
        try:
            style = ttk.Style()
            style.configure(
                "Treeview",
                font=font_scaled("Microsoft YaHei", 9),
                rowheight=px(20),
            )
            style.configure(
                "Treeview.Heading",
                font=font_scaled("Microsoft YaHei", 9, "bold"),
                rowheight=px(24),
            )
        except Exception:
            pass

        self.log_frame = ttk.LabelFrame(self.switch_frame, text="日志", padding=px(2))

        # 先初始化 logger 配置（从 log_config.ini 加载，以便滑动条反映真实默认级别）
        # 然后注册 raw_append，最后再构建滑动条 UI
        logger_utils.init_logger(callback=None)
        logger_utils.set_raw_append_callback(self._append_log_line)

        self._build_log_controls(self.log_frame)
        self.log_text = tk.Text(self.log_frame, height=18, font=font_scaled("Consolas", 9), state=tk.NORMAL)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=px(3), pady=(px(2), px(3)))
        self.log_text.config(state=tk.DISABLED)
        self.log_text.bind("<Control-c>", self._copy_log)
        self.log_text.bind("<Button-3>", self._show_log_menu)
        self.log_visible = False

        self.bottom_frame = ttk.Frame(main)
        self.bottom_frame.grid(row=1, column=0, sticky="ew")

        # 统一横幅通知（所有模块共享）：使用 Toplevel 悬浮在主窗口之上
        self._toast_window = None
        self._toast_label = None
        self._toast_after_id = None

        self.progress_frame = ttk.Frame(self.bottom_frame)
        self.progress_frame.pack(fill=tk.X, pady=(0, px(2)))
        self.progress_bar = ttk.Progressbar(self.progress_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_label = ttk.Label(self.progress_frame, text="", anchor=tk.CENTER, width=15)
        self.progress_label.pack(side=tk.LEFT, padx=(px(2), 0))
        self.log_toggle_btn = ttk.Button(self.progress_frame, text="日志", command=self._toggle_log, width=5)
        self.log_toggle_btn.pack(side=tk.RIGHT, padx=(px(2), 0))

        self.status_bar = ttk.Frame(self.bottom_frame)
        self.status_bar.pack(fill=tk.X)
        self.status_label = ttk.Label(self.status_bar, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(fill=tk.X, side=tk.LEFT)
        admin_label = ttk.Label(self.status_bar, text="管理员" if self._is_admin() else "普通用户", relief=tk.SUNKEN, anchor=tk.E)
        admin_label.pack(fill=tk.X, side=tk.RIGHT)

    def _toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.content_frame.pack_forget()
            self.log_frame.pack(fill=tk.BOTH, expand=True)
            self.log_toggle_btn.config(text="界面")
        else:
            self.log_frame.pack_forget()
            self.content_frame.pack(fill=tk.BOTH, expand=True)
            self.log_toggle_btn.config(text="日志")

    # ---------- 日志级别控制区：单一条目滑动条 + 4 彩色圆点 ----------

    def _build_log_controls(self, parent):
        """日志面板顶部：左侧级别滑动条，右侧清空/重刷按钮。"""
        ctrl_frame = ttk.Frame(parent)
        ctrl_frame.pack(fill=tk.X, padx=px(6), pady=(px(6), px(3)))

        # --- 左侧：彩色圆点滑动条 ---
        dot_frame = tk.Frame(ctrl_frame, bg="#f5f5f5", highlightthickness=1,
                             highlightbackground="#d0d0d0")
        dot_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 说明标签
        ttk.Label(dot_frame, text="日志级别：", background="#f5f5f5").pack(
            side=tk.LEFT, padx=(px(8), px(4)), pady=px(6)
        )

        # 使用 Canvas 绘制轨道 + 4 彩色圆点
        slider_w = px(260)
        slider_h = px(30)
        self._log_level_canvas = tk.Canvas(
            dot_frame, width=slider_w, height=slider_h,
            bg="#f5f5f5", highlightthickness=0, cursor="hand2"
        )
        self._log_level_canvas.pack(side=tk.LEFT, padx=px(4), pady=px(4))

        self._slider_y = slider_h // 2
        self._slider_margin = px(16)
        self._slider_xs = []
        self._slider_level_names = []
        self._slider_colors = []
        self._slider_selected_idx = 0

        self._slider_label_var = tk.StringVar(value=logger_utils.get_global_level_name())
        self._slider_label = tk.Label(
            dot_frame, textvariable=self._slider_label_var,
            width=8, background="#f5f5f5",
            foreground=logger_utils.LEVEL_ORDER[
                max(0, [n for n, _, _ in logger_utils.LEVEL_ORDER].index(
                    logger_utils.get_global_level_name()))
            ][2],
            font=font_scaled("", 9, "bold"),
        )
        self._slider_label.pack(side=tk.LEFT, padx=(px(6), px(8)))

        # 绘制圆点（会通过 _update_slider_selected 更新文本标签）
        self._draw_slider(initial_name=logger_utils.get_global_level_name())

        # 鼠标按下/拖动：调整选中
        self._log_level_canvas.bind("<Button-1>", self._on_slider_click)
        self._log_level_canvas.bind("<B1-Motion>", self._on_slider_click)

        # --- 右侧：清空日志按钮 ---
        right = tk.Frame(ctrl_frame, bg="#f5f5f5")
        right.pack(side=tk.RIGHT, padx=(px(6), 0))
        btn_wrap = tk.Frame(right, bg="#f5f5f5")
        btn_wrap.pack(side=tk.RIGHT, pady=0)
        ttk.Button(btn_wrap, text="清空日志", command=self._clear_log_and_buffer,
                   width=8).pack(side=tk.LEFT, padx=px(3))

    def _draw_slider(self, initial_name):
        c = self._log_level_canvas
        w = int(c["width"])
        y = self._slider_y
        margin = self._slider_margin
        dot_r = px(7)

        c.delete("all")
        c.create_line(margin, y, w - margin, y, fill="#d0d0d0", width=px(3))

        n_points = len(logger_utils.LEVEL_ORDER)
        step = (w - 2 * margin) / (n_points - 1)
        self._slider_xs = [int(margin + i * step) for i in range(n_points)]
        self._slider_level_names = [name for name, _, _ in logger_utils.LEVEL_ORDER]
        self._slider_colors = [color for _, _, color in logger_utils.LEVEL_ORDER]

        for i, x in enumerate(self._slider_xs):
            color = self._slider_colors[i]
            c.create_oval(x - dot_r, y - dot_r, x + dot_r, y + dot_r,
                          fill="white", outline=color, width=px(1), tags=f"dot{i}")

        try:
            initial_idx = self._slider_level_names.index(initial_name)
        except ValueError:
            initial_idx = 0
        self._slider_selected_idx = initial_idx
        self._update_slider_selected()

    def _update_slider_selected(self):
        c = self._log_level_canvas
        y = self._slider_y
        dot_r = px(7)
        for i, x in enumerate(self._slider_xs):
            color = self._slider_colors[i]
            if i == self._slider_selected_idx:
                c.itemconfig(f"dot{i}", fill=color, outline="white", width=px(2))
                c.coords(f"dot{i}", x - dot_r, y - dot_r, x + dot_r, y + dot_r)
            else:
                c.itemconfig(f"dot{i}", fill="white", outline=color, width=px(1))
                c.coords(f"dot{i}", x - dot_r, y - dot_r, x + dot_r, y + dot_r)

        name = self._slider_level_names[self._slider_selected_idx]
        color = self._slider_colors[self._slider_selected_idx]
        self._slider_label_var.set(name)
        try:
            self._slider_label.config(foreground=color)
        except Exception:
            pass

    def _on_slider_click(self, event):
        x = event.x
        best_i = 0
        best_d = abs(x - self._slider_xs[0])
        for i, xi in enumerate(self._slider_xs):
            d = abs(x - xi)
            if d < best_d:
                best_d = d
                best_i = i
        if best_i == self._slider_selected_idx:
            return
        self._slider_selected_idx = best_i
        self._update_slider_selected()
        level_name = self._slider_level_names[best_i]
        logger_utils.set_log_level(level_name)
        self._rerender_log_text()

    def _on_global_level_changed(self):
        level_name = self._global_level_var.get()
        logger_utils.set_log_level(level_name)
        self._rerender_log_text()

    def _rerender_log_text(self):
        """根据当前级别，把缓冲里满足条件的行重刷到 UI 文本框。"""
        lines = logger_utils.get_filtered_lines()
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        if lines:
            self.log_text.insert(tk.END, "\n".join(lines) + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _clear_log_and_buffer(self):
        logger_utils.clear_buffer()
        self._clear_log()

    # ---------- 日志输出 ----------

    def _append_log_line(self, line):
        """向 UI 文本框追加一行（仅负责追加文本，不会递归写回日志）"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _log(self, msg, update_status=True):
        """主日志输出：统一路由到 logger_utils.log。
        logger_utils.log 会自行写入缓冲并调用 raw_append 追加到文本框。
        """
        logger_utils.log("app", "DEBUG", msg)
        if update_status:
            self._set_status(msg)
        try:
            self.root.update()
        except Exception:
            pass

    def _init_modules(self):
        # 先创建占位标签页，确保标签页显示
        self._placeholder_tabs = {}
        tab_names = ["镜像编辑", "启动测试", "引导管理", "关于软件"]
        for i, name in enumerate(tab_names):
            frame = ttk.Frame(self.tab_control)
            self.tab_control.add(frame, text=name)
            self._placeholder_tabs[i] = frame

        # 延迟初始化模块内容
        self.editor = None
        self.boot_mgr = None
        self.boot_test = None
        self._editor_loaded = False
        self._boot_mgr_loaded = False
        self._boot_test_loaded = False
        self._bcd_loaded = False
        self._about_loaded = False

        # 懒加载引导环境检测器
        self._boot_detector_lazy = None
        self._boot_env_cache = None

        self.tab_control.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.root.after(50, self._load_editor_tab)

    def _log_only(self, msg):
        """仅记录日志，不更新状态栏"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update()

    def _replace_placeholder(self, tab_index):
        if tab_index in self._placeholder_tabs:
            old_frame = self._placeholder_tabs[tab_index]
            current_index = self.tab_control.index(self.tab_control.select())
            self.tab_control.forget(old_frame)
            del self._placeholder_tabs[tab_index]
            if current_index > tab_index:
                self.tab_control.select(current_index - 1)
            else:
                self.tab_control.select(current_index)

    def _load_editor_tab(self):
        """延迟加载镜像编辑模块"""
        if self._editor_loaded:
            return
        self._editor_loaded = True
        self._log("正在加载镜像编辑模块...")
        tab_frame = self._placeholder_tabs.get(0)
        if tab_frame is None:
            tab_frame = ttk.Frame(self.tab_control)
            self.tab_control.add(tab_frame, text="镜像编辑")
        
        self.editor = WimEditor(
            parent=self.tab_control,
            root=self.root,
            base_dir=self.base_dir,
            data_dir=self.data_dir,
            wimlib_exe=self.wimlib_exe,
            dism_exe=self.dism_exe,
            sevenz_exe=self.sevenz_exe,
            log_callback=self._log,
            status_callback=self._set_status,
            progress_callback=self._set_progress,
            toast_callback=self._toast,
            tab_frame=tab_frame,
            icon_path=self._get_icon_path(),
        )
        self._log("镜像编辑模块加载完成")

    def _load_boot_mgr_tab(self):
        """延迟加载引导管理模块"""
        if self._boot_mgr_loaded:
            return
        self._boot_mgr_loaded = True
        self._log("正在加载引导管理模块...")
        tab_frame = self._placeholder_tabs.get(2)
        if tab_frame is None:
            tab_frame = ttk.Frame(self.tab_control)
            self.tab_control.add(tab_frame, text="引导管理")
        
        self.boot_mgr = BootManager(
            parent=self.tab_control,
            root=self.root,
            base_dir=self.base_dir,
            data_dir=self.data_dir,
            wimlib_exe=self.wimlib_exe,
            dism_exe=self.dism_exe,
            sevenz_exe=self.sevenz_exe,
            log_callback=self._log,
            status_callback=self._set_status,
            progress_callback=self._set_progress,
            tab_frame=tab_frame,
            icon_path=self._get_icon_path(),
            boot_env_cache=self._boot_env_cache,
            boot_detector=self.boot_detector,
        )
        self._log("引导管理模块加载完成")

    def _load_boot_test_tab(self):
        """延迟加载启动测试模块"""
        if self._boot_test_loaded:
            return
        self._boot_test_loaded = True
        self._log("正在加载启动测试模块...")
        tab_frame = self._placeholder_tabs.get(1)
        if tab_frame is None:
            tab_frame = ttk.Frame(self.tab_control)
            self.tab_control.add(tab_frame, text="启动测试")
        
        self.boot_test = BootTest(
            parent=self.tab_control,
            root=self.root,
            base_dir=self.base_dir,
            data_dir=self.data_dir,
            sevenz_exe=self.sevenz_exe,
            wimlib_exe=self.wimlib_exe,
            dism_exe=self.dism_exe,
            log_callback=self._log,
            status_callback=self._set_status,
            progress_callback=self._set_progress,
            switch_to_bcd_callback=self._switch_to_bcd_tab,
            boot_manager_callback=self._get_or_create_boot_manager,
            tab_frame=tab_frame,
            icon_path=self._get_icon_path(),
            boot_env_cache=self._boot_env_cache,
            boot_detector=self.boot_detector,
        )
        self._log("启动测试模块加载完成")

    @property
    def boot_detector(self):
        """懒加载引导环境检测器。仅在首次访问（比如切到启动测试/引导管理标签）时才 import + 实例化。"""
        if self._boot_detector_lazy is None:
            from boot_utils import BootEnvironmentDetector
            self._boot_detector_lazy = BootEnvironmentDetector(log_callback=self._log)
        return self._boot_detector_lazy

    def _on_tab_changed(self, event=None):
        tab_index = self.tab_control.index(self.tab_control.select())
        if tab_index == 0 and not self._editor_loaded:
            self._load_editor_tab()
        elif tab_index == 1 and not self._boot_test_loaded:
            self._load_boot_test_tab()
        elif tab_index == 2:
            if not self._boot_mgr_loaded:
                self._load_boot_mgr_tab()
                self.root.after(100, self.boot_mgr._auto_load_bcd)
            else:
                self.root.after(100, self.boot_mgr._refresh_bcd_list)
        elif tab_index == 3 and not self._about_loaded:
            self._load_about_tab()

    def _load_about_tab(self):
        """加载关于标签页"""
        if self._about_loaded:
            return
        self._about_loaded = True
        
        tab_frame = self._placeholder_tabs.get(3)
        if not tab_frame:
            # 如果占位符已被删除，创建新框架
            tab_frame = ttk.Frame(self.tab_control)
            self.tab_control.add(tab_frame, text="关于软件")
        
        # 主容器
        main_container = ttk.Frame(tab_frame, padding=px(15))
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # 版本信息区域
        version_frame = ttk.LabelFrame(main_container, text="版本信息", padding=px(10))
        version_frame.pack(fill=tk.X, pady=(0, px(10)))
        
        # 软件名称行（带版本号和检查更新按钮）
        name_row = ttk.Frame(version_frame)
        name_row.pack(fill=tk.X, pady=px(2))
        ttk.Label(name_row, text="软件名称：", width=12, anchor=tk.E, font=font_scaled("", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(name_row, text="映像编辑辅助工具", anchor=tk.W).pack(side=tk.LEFT, padx=(0, px(10)))
        ttk.Label(name_row, text="版本号：", width=8, anchor=tk.E, font=font_scaled("", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(name_row, text=APP_VERSION, anchor=tk.W).pack(side=tk.LEFT, padx=(0, px(15)))
        if getattr(self, 'update_checker', None) is not None:
            ttk.Button(name_row, text="检查更新", command=self._on_check_update_clicked, width=10).pack(side=tk.RIGHT, padx=px(5))
        
        # 电子邮箱行
        email_row = ttk.Frame(version_frame)
        email_row.pack(fill=tk.X, pady=px(2))
        ttk.Label(email_row, text="电子邮箱：", width=12, anchor=tk.E, font=font_scaled("", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(email_row, text="hack003@163.com", anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 免责声明区域
        disclaimer_frame = ttk.LabelFrame(main_container, text="免责声明", padding=px(5))
        disclaimer_frame.pack(fill=tk.BOTH, expand=True, pady=(0, px(10)))
        
        disclaimer_scroll = ttk.Scrollbar(disclaimer_frame)
        disclaimer_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        disclaimer_text_widget = tk.Text(
            disclaimer_frame,
            wrap=tk.CHAR,
            font=font_scaled("", 9),
            spacing1=px(3),
            spacing2=px(2),
            spacing3=px(3),
            relief=tk.FLAT,
            height=8,
            yscrollcommand=disclaimer_scroll.set
        )
        disclaimer_text_widget.pack(fill=tk.BOTH, expand=True, padx=px(5), pady=px(5))

        # 配置颜色标签
        disclaimer_text_widget.tag_configure("header", foreground="#1a73e8", font=font_scaled("", 10, "bold"))
        disclaimer_text_widget.tag_configure("highlight", foreground="#d93025")
        disclaimer_text_widget.tag_configure("recommend", foreground="#e37318")
        disclaimer_text_widget.tag_configure("warning_header", foreground="#d93025", font=font_scaled("", 10, "bold"))
        disclaimer_text_widget.tag_configure("notice", foreground="#70757a")

        tw = disclaimer_text_widget
        tw.insert(tk.END, "【关于本软件】\n", "header")
        tw.insert(tk.END, "本工具的开发初衷，源于长期以来对")
        tw.insert(tk.END, "「秋刀鱼 Wit」（WIT）", "highlight")
        tw.insert(tk.END, "的依赖与使用。在此谨向 WIT 的开发者致以诚挚的感谢——WIT 是一款功能强大且稳定可靠的全能工具，涵盖系统安装备份、系统优化、数据迁移、磁盘克隆与拷贝、分区复制等几乎所有能想到的磁盘与系统管理功能，映像编辑只是其中一项。它一直是我日常工作中的首选。\n\n")
        tw.insert(tk.END, "由于近期 WIT 未发布新版，软件转为标准版后部分功能模块不可用，而映像编辑又是我日常工作中频繁使用的操作，因此萌生了自行开发本软件的想法。其主要目的是满足个人使用需求，顺带集成了启动测试与引导管理功能，以方便日常测试工作。\n\n")
        tw.insert(tk.END, "在此郑重推荐：若您需要专业、完整的映像编辑解决方案，仍建议优先使用 WIT，其功能的全面性与稳定性均表现出色。\n\n", "recommend")
        tw.insert(tk.END, "【使用须知】\n", "warning_header")
        tw.insert(tk.END,
            "1. 本软件处于初期开发阶段，可能存在未知Bug，请谨慎使用。\n"
            "2. 在使用本软件前，请务必备份重要数据，以防数据丢失或损坏。\n"
            "3. 本软件仅供学习和研究使用，使用者应自行承担使用风险。\n"
            "4. 开发者不对软件的适用性、可靠性、安全性作任何明示或暗示的保证。\n"
            "5. 因使用本软件而导致的任何数据丢失、系统损坏或其他损失，开发者不承担任何责任。\n"
            "6. 使用本软件即表示您已阅读并同意本免责声明的所有内容。\n",
            "notice"
        )
        tw.config(state=tk.DISABLED)
        
        disclaimer_scroll.config(command=disclaimer_text_widget.yview)

    def _is_admin(self):
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False

    def _decode(self, data):
        if isinstance(data, bytes):
            for enc in ['gbk', 'utf-8', 'gb2312', 'cp936', 'latin-1']:
                try:
                    return data.decode(enc)
                except:
                    continue
            return data.decode('gbk', errors='replace')
        return str(data)

    def _on_close(self):
        """程序退出时统一卸载ESP分区（只有在真的实例化过才卸载，避免启动就import）"""
        if self._boot_detector_lazy is not None:
            try:
                from boot_utils import BootEnvironmentDetector
                BootEnvironmentDetector.unmount_efi_global()
            except Exception:
                pass
        self.root.destroy()

    def _copy_log(self, event=None):
        try:
            sel = self.log_text.get("sel.first", "sel.last")
            self.root.clipboard_clear()
            self.root.clipboard_append(sel)
        except tk.TclError:
            all_text = self.log_text.get("1.0", tk.END)
            self.root.clipboard_clear()
            self.root.clipboard_append(all_text)
        return "break"

    def _show_log_menu(self, event):
        menu = tk.Menu(self.log_text, tearoff=0)
        menu.add_command(label="复制", command=self._copy_log)
        menu.add_command(label="全选", command=self._select_all_log)
        menu.add_command(label="清空日志", command=self._clear_log)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _select_all_log(self):
        self.log_text.tag_add(tk.SEL, "1.0", tk.END)
        self.log_text.mark_set(tk.INSERT, "1.0")
        self.log_text.see(tk.INSERT)
        return "break"

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
        self._set_status("日志已清空")

    def _set_progress(self, value, text=""):
        self.progress_bar['value'] = value
        if text:
            self.progress_label.config(text=text)
            # 同步把进度信息显示到状态栏，让用户在底部一眼看到
            if "%" in text or "已下载" in text:
                self.status_label.config(text="下载更新中… " + text)
        self.root.update()

    def _clear_progress(self):
        self.progress_bar['value'] = 0
        self.progress_label.config(text="")
        self.root.update()

    def _log(self, msg, update_status=True):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        if update_status:
            self._set_status(msg)
        self.root.update()

    def _set_status(self, msg):
        self.status_label.config(text=msg)
        self.root.update()

    def _toast(self, msg, kind="info", duration_ms=2500):
        """统一横幅通知：使用 Toplevel 悬浮在主窗口之上（不挤占布局、不下压进度条/状态栏）。
        默认显示时间 2.5 秒。

        kind: "info" (蓝色) / "success" (绿色) / "warning" (橙色) / "error" (红色)
        """
        colors = {
            "info":    ("#3a86ff", "white"),
            "success": ("#2ec4b6", "white"),
            "warning": ("#ff9f1c", "black"),
            "error":   ("#e71d36", "white"),
        }
        bg, fg = colors.get(kind, colors["info"])

        if self._toast_window is None or not self._toast_window.winfo_exists():
            try:
                self._toast_window = tk.Toplevel(self.root)
            except Exception:
                return
            self._toast_window.overrideredirect(True)
            self._toast_window.attributes("-topmost", True)
            self._toast_window.attributes("-alpha", 0.95)
            self._toast_label = tk.Label(
                self._toast_window,
                text="",
                bg=bg,
                fg=fg,
                font=font_scaled("Microsoft YaHei", 10),
                anchor=tk.W,
                justify=tk.LEFT,
                padx=px(12),
                pady=px(5),
            )
            self._toast_label.pack(fill=tk.BOTH, expand=True)

        self._toast_label.config(text=msg, bg=bg, fg=fg)

        try:
            self.root.update_idletasks()
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            root_w = self.root.winfo_width()
            root_h = self.root.winfo_height()

            margin_x = px(10)
            margin_y = px(4)
            self._toast_window.update_idletasks()
            try:
                bw = max(px(200), root_w - margin_x * 2)
                bh = self._toast_label.winfo_reqheight() + px(6)
            except Exception:
                bw = root_w - margin_x * 2
                bh = px(32)
            x = root_x + margin_x
            y = root_y + root_h - bh - margin_y - px(24)
            self._toast_window.geometry(f"{bw}x{bh}+{x}+{y}")
            self._toast_window.deiconify()
            try:
                self._toast_window.lift()
            except Exception:
                pass
        except Exception:
            pass

        if self._toast_after_id:
            try:
                self.root.after_cancel(self._toast_after_id)
            except Exception:
                pass
        self._toast_after_id = None

        def _hide():
            try:
                if self._toast_window is not None and self._toast_window.winfo_exists():
                    self._toast_window.withdraw()
            except Exception:
                pass
            self._toast_after_id = None

        self._toast_after_id = self.root.after(duration_ms, _hide)

    def _get_icon_path(self):
        """获取图标文件路径（兼容冻结环境）"""
        if getattr(sys, 'frozen', False):
            return os.path.join(sys._MEIPASS, "wim.ico")
        return os.path.join(self.base_dir, "resources", "wim.ico")

    def _set_icon(self, window):
        """设置窗口图标（增加重试机制：避免 Defender 扫描导致的临时文件锁定）"""
        icon_path = self._get_icon_path()
        if os.path.exists(icon_path):
            for attempt in range(5):
                try:
                    window.iconbitmap(icon_path)
                    return
                except Exception:
                    import time as _icon_time
                    _icon_time.sleep(1)

    def _switch_to_bcd_tab(self):
        self.tab_control.select(2)
        if self._boot_mgr_loaded and hasattr(self, 'boot_mgr'):
            self.boot_mgr._refresh_bcd_list()

    def _get_or_create_boot_manager(self):
        """获取或创建BootManager实例"""
        if not self._boot_mgr_loaded:
            self._load_boot_mgr_tab()
        return getattr(self, 'boot_mgr', None)

    # ===========================================================
    # 自动更新相关
    # ===========================================================
    def _on_check_update_clicked(self):
        """「检查更新」按钮的点击处理"""
        if self.update_checker is None:
            messagebox.showinfo("检查更新", "自动更新模块未就绪", parent=self.master)
            return
        if self.update_checker.is_busy():
            self._toast("正在处理上次的请求，请稍候...", "warning")
            return

        def _on_result(has_update, latest_version, message, update_log_text="", info=None):
            if has_update:
                banner_title = "发现新版本：" + str(latest_version)
                self._set_status(banner_title)

                toast_msg = banner_title
                if update_log_text:
                    toast_msg = banner_title + "\n更新说明：\n" + str(update_log_text)
                self._toast(toast_msg, "success", duration_ms=10000)

                self.root.after(600, self._apply_update_and_restart)
            else:
                self._set_status(message)
                self._toast(message, "info")

        self.update_checker.check_update_async(on_result_callback=_on_result)

    def _apply_update_and_restart(self):
        """执行下载并更新流程（下载完成后自动退出、替换、重启）"""
        if self.update_checker is None or self.update_checker.is_busy():
            return

        def _on_finish(success, message, updater_bat):
            if success and updater_bat:
                self._set_status("更新包下载完成，即将退出并更新…")
                self._toast("更新包下载完成，即将退出并更新", "success", duration_ms=2500)

                def _do_exit_and_update():
                    try:
                        from boot_utils import BootEnvironmentDetector
                        BootEnvironmentDetector.unmount_efi_global()
                    except Exception:
                        pass
                    from update import launch_updater
                    if launch_updater(updater_bat):
                        try:
                            self.root.destroy()
                        except Exception:
                            pass
                        sys.exit(0)
                    else:
                        messagebox.showerror("更新失败", "无法启动更新脚本，请手动下载新版本。", parent=self.master)

                self.root.after(2200, _do_exit_and_update)
            else:
                self._set_status("更新失败：" + message)
                self._toast("更新失败：" + message, "error")

        self.update_checker.do_update_async(on_finish_callback=_on_finish)


def _ensure_admin():
    """检查当前是否以管理员身份运行。若不是，则以管理员身份重启当前程序。"""
    if _is_admin_static():
        return True
    try:
        import ctypes
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
            params = " ".join(f'"{p}"' for p in sys.argv[1:])
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe_path, params, None, 1
            )
        else:
            script = os.path.abspath(sys.argv[0])
            params = " ".join(f'"{p}"' for p in sys.argv[1:])
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{script}" {params}', None, 1
            )
        return False
    except Exception:
        return True


def _is_admin_static():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def main():
    if not _ensure_admin():
        sys.exit(0)
    root = tk.Tk()
    app = WIMTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()