# -*- coding: utf-8 -*-
"""镜像编辑模块 - 挂载/卸载、镜像优化、信息处理"""

import os
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import tempfile
import threading
import queue
from file_searcher import search_file
from dpi_utils import px, font_scaled
import logger_utils


class WimEditor:
    def __init__(self, parent, root, base_dir, data_dir, wimlib_exe, dism_exe, sevenz_exe, log_callback, status_callback, progress_callback, toast_callback=None, tab_frame=None, icon_path=None):
        self.root = root
        self.base_dir = base_dir
        self.data_dir = data_dir
        self.wimlib_exe = wimlib_exe
        self.dism_exe = dism_exe
        self.sevenz_exe = sevenz_exe
        self.icon_path = icon_path
        self._log = log_callback
        self._set_status = status_callback
        self._set_progress = progress_callback
        self._toast_callback = toast_callback  # 统一横幅提醒回调
        self._clear_progress = lambda: progress_callback(0, "")

        # 统一日志系统：初始化并让 logger_utils 也回写到 UI
        logger_utils.init_logger(callback=log_callback)

        # 横幅通知状态
        self._banner_label = None
        self._banner_after_id = None

        # 线程安全队列，用于后台任务与主线程通信
        self._task_queue = queue.Queue()
        self._start_queue_processor()

        self.image_file = tk.StringVar()
        self.img_index = tk.StringVar(value="1")
        self.image_info = []
        self.mount_list = []
        self.temp_mount_dir = None

        # 镜像信息表单变量
        self.display_name = tk.StringVar()
        self.display_desc = tk.StringVar()
        self.image_name = tk.StringVar()
        self.image_desc = tk.StringVar()
        self.other_info = tk.StringVar()

        # 编辑状态
        self.edit_mode = False
        self.edit_backup = {}

        # 如果提供了预创建的框架，直接使用；否则在parent中创建新标签页
        if tab_frame is not None:
            self.parent = tab_frame
        else:
            self.parent = ttk.Frame(parent)
            parent.add(self.parent, text="镜像编辑")
        
        self._build_ui()

    def _start_queue_processor(self):
        """启动队列处理器，在主线程中处理后台任务的消息"""
        def process():
            try:
                while True:
                    msg_type, *args = self._task_queue.get_nowait()
                    if msg_type == "log":
                        self._log(args[0])
                    elif msg_type == "status":
                        self._set_status(args[0])
                    elif msg_type == "progress":
                        self._set_progress(args[0], args[1] if len(args) > 1 else "")
                    elif msg_type == "toast":
                        # toast(msg, kind, duration_ms)
                        msg = args[0] if len(args) > 0 else ""
                        kind = args[1] if len(args) > 1 else "info"
                        duration = args[2] if len(args) > 2 else 1500
                        self._toast(msg, kind, duration)
                    elif msg_type == "done":
                        args[0]()  # 回调函数
            except queue.Empty:
                pass
            self.root.after(50, process)
        process()

    def _scan_existing_mounts(self):
        """扫描已存在的挂载点并加载到列表"""
        try:
            dism = self._get_dism_exe()
            ok, out = self._run_get([dism, "/Get-MountedWimInfo"], "扫描挂载")
            if not ok or not out:
                return
            # 解析 DISM 输出，提取挂载目录、映像文件、索引
            # DISM 中文输出格式:
            #   安装目录: D:\xxx
            #   映像文件: D:\xxx.wim
            #   映像索引: 1
            current = {}
            for line in out.split("\n"):
                line = line.strip()
                if not line:
                    if current.get("mount_dir"):
                        idx = current.get("index", "1")
                        self.mount_list.append({
                            "idx": str(len(self.mount_list) + 1),
                            "mount_dir": current["mount_dir"],
                            "image_file": current.get("image_file", ""),
                            "index": idx,
                            "status": "正常"
                        })
                        self.mount_tree.insert("", tk.END, values=(
                            self.mount_list[-1]["idx"],
                            self.mount_list[-1]["mount_dir"],
                            self.mount_list[-1]["image_file"],
                            idx,
                            "正常"
                        ))
                    current = {}
                    continue
                # 匹配 "安装目录: xxx" 或 "Mount Dir: xxx" 或 "挂载目录: xxx"
                if "安装目录" in line or "Mount Dir" in line or "挂载目录" in line:
                    current["mount_dir"] = line.split(":", 1)[1].strip() if ":" in line else ""
                elif "映像文件" in line or "Wim File" in line:
                    current["image_file"] = line.split(":", 1)[1].strip() if ":" in line else ""
                elif "映像索引" in line or "Index" in line:
                    current["index"] = line.split(":", 1)[1].strip() if ":" in line else "1"
            # 处理最后一个
            if current.get("mount_dir"):
                idx = current.get("index", "1")
                self.mount_list.append({
                    "idx": str(len(self.mount_list) + 1),
                    "mount_dir": current["mount_dir"],
                    "image_file": current.get("image_file", ""),
                    "index": idx,
                    "status": "正常"
                })
                self.mount_tree.insert("", tk.END, values=(
                    self.mount_list[-1]["idx"],
                    self.mount_list[-1]["mount_dir"],
                    self.mount_list[-1]["image_file"],
                    idx,
                    "正常"
                ))
            if self.mount_list:
                self._log(f"发现 {len(self.mount_list)} 个已挂载点")
        except Exception as e:
            self._log(f"扫描挂载点失败: {e}")

    def _build_ui(self):
        self.parent.configure(padding=px(3))
        tab1 = self.parent

        # 第一行：映像文件
        f1 = ttk.Frame(tab1)
        f1.pack(fill=tk.X, pady=(0, px(3)))
        ttk.Label(f1, text="镜像文件:").pack(side=tk.LEFT, padx=(0, px(2)))
        ttk.Entry(f1, textvariable=self.image_file, width=38).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, px(2)))
        ttk.Button(f1, text="搜索", command=self._auto_search_wim, width=5).pack(side=tk.LEFT, padx=px(1))
        ttk.Button(f1, text="浏览", command=self._browse_image, width=5).pack(side=tk.LEFT)

        # 第二行：操作按钮一行
        f2 = ttk.Frame(tab1)
        f2.pack(fill=tk.X, pady=(0, px(3)))

        self.btn_mount = ttk.Button(f2, text="镜像挂载", command=self._mount, width=10)
        self.btn_mount.pack(side=tk.LEFT, padx=px(1))
        self.btn_commit = ttk.Button(f2, text="保存卸载", command=lambda: self._unmount(True), width=10)
        self.btn_commit.pack(side=tk.LEFT, padx=px(1))
        self.btn_discard = ttk.Button(f2, text="放弃卸载", command=lambda: self._unmount(False), width=10)
        self.btn_discard.pack(side=tk.LEFT, padx=px(1))
        self.btn_cleanup = ttk.Button(f2, text="清理卸载", command=self._cleanup_all, width=10)
        self.btn_cleanup.pack(side=tk.LEFT, padx=px(1))
        ttk.Button(f2, text="恢复挂载", command=self._scan_existing_mounts, width=10).pack(side=tk.LEFT, padx=px(1))

        # 第三行：镜像信息展示和修改 + 右侧操作
        f3 = ttk.Frame(tab1)
        f3.pack(fill=tk.X, pady=(0, px(3)))

        # 左侧：镜像信息表单
        info_frame = ttk.LabelFrame(f3, text="镜像信息展示和修改", padding=px(3))
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 索引列表行
        idx_row = ttk.Frame(info_frame)
        idx_row.pack(fill=tk.X, pady=px(1))
        ttk.Label(idx_row, text="索引列表:", width=8).pack(side=tk.LEFT)
        self.idx_combo = ttk.Combobox(idx_row, textvariable=self.img_index, width=30, state="readonly")
        self.idx_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=px(2))
        self.idx_arch = ttk.Label(idx_row, text="", width=6)
        self.idx_arch.pack(side=tk.LEFT, padx=px(1))
        self.idx_version = ttk.Label(idx_row, text="", width=8)
        self.idx_version.pack(side=tk.LEFT, padx=px(1))

        # 显示名称
        dn_row = ttk.Frame(info_frame)
        dn_row.pack(fill=tk.X, pady=px(1))
        ttk.Label(dn_row, text="显示名称:", width=8).pack(side=tk.LEFT)
        self.display_name_entry = ttk.Entry(dn_row, textvariable=self.display_name, width=35, state="readonly")
        self.display_name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=px(2))

        # 显示描述
        dd_row = ttk.Frame(info_frame)
        dd_row.pack(fill=tk.X, pady=px(1))
        ttk.Label(dd_row, text="显示描述:", width=8).pack(side=tk.LEFT)
        self.display_desc_entry = ttk.Entry(dd_row, textvariable=self.display_desc, width=35, state="readonly")
        self.display_desc_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=px(2))

        # 映像名称
        in_row = ttk.Frame(info_frame)
        in_row.pack(fill=tk.X, pady=px(1))
        ttk.Label(in_row, text="映像名称:", width=8).pack(side=tk.LEFT)
        self.image_name_entry = ttk.Entry(in_row, textvariable=self.image_name, width=35, state="readonly")
        self.image_name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=px(2))

        # 映像描述
        id_row = ttk.Frame(info_frame)
        id_row.pack(fill=tk.X, pady=px(1))
        ttk.Label(id_row, text="映像描述:", width=8).pack(side=tk.LEFT)
        self.image_desc_entry = ttk.Entry(id_row, textvariable=self.image_desc, width=35, state="readonly")
        self.image_desc_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=px(2))

        # 其他信息
        oi_row = ttk.Frame(info_frame)
        oi_row.pack(fill=tk.X, pady=px(1))
        ttk.Label(oi_row, text="其他信息:", width=8).pack(side=tk.LEFT)
        ttk.Label(oi_row, textvariable=self.other_info, width=35, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=px(2))

        # 右侧：操作按钮
        right_frame = ttk.Frame(f3)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(px(3), 0))

        ttk.Button(right_frame, text="镜像优化", command=self._optimize, width=10).pack(pady=px(2))
        ttk.Button(right_frame, text="信息处理", command=self._enable_edit, width=10).pack(pady=px(2))
        ttk.Button(right_frame, text="提交", command=self._save_info_changes, width=10).pack(pady=px(2))
        ttk.Button(right_frame, text="取消", command=self._cancel_edit, width=10).pack(pady=px(2))

        self.idx_combo.bind("<<ComboboxSelected>>", self._on_idx_change)

        # 第四行：挂载列表（初始紧凑高度，不膨胀占用其他控件空间）
        f4 = ttk.LabelFrame(tab1, text="挂载列表", padding=px(3))
        f4.pack(fill=tk.X, pady=px(2))

        columns = ("idx", "mount_dir", "image_file", "index", "status")
        self.mount_tree = ttk.Treeview(f4, columns=columns, show="headings", height=5)

        self.mount_tree.heading("idx", text="序号")
        self.mount_tree.heading("mount_dir", text="挂载目录")
        self.mount_tree.heading("image_file", text="映像文件")
        self.mount_tree.heading("index", text="卷号")
        self.mount_tree.heading("status", text="状态")

        self.mount_tree.column("idx", width=px(45), minwidth=px(30), anchor=tk.CENTER, stretch=False)
        self.mount_tree.column("mount_dir", width=px(160), minwidth=px(80), anchor=tk.W, stretch=True)
        self.mount_tree.column("image_file", width=px(180), minwidth=px(80), anchor=tk.W, stretch=True)
        self.mount_tree.column("index", width=px(45), minwidth=px(30), anchor=tk.CENTER, stretch=False)
        self.mount_tree.column("status", width=px(70), minwidth=px(50), anchor=tk.CENTER, stretch=False)

        scrollbar = ttk.Scrollbar(f4, orient=tk.VERTICAL, command=self.mount_tree.yview)
        self.mount_tree.configure(yscrollcommand=scrollbar.set)

        self.mount_tree.pack(side=tk.LEFT, fill=tk.X)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.mount_tree.bind("<Double-1>", self._on_mount_dblclick)
        self.mount_tree.bind("<Double-1>", self._on_mount_dblclick)

        # 横幅通知（兼容独立运行时的兜底提示，使用 Toplevel 悬浮不挤占布局）
        self._banner_window = None
        self._banner_label = None

    def _on_mount_dblclick(self, event):
        """双击挂载列表：双击映像文件列自动加载信息，双击挂载目录列打开文件夹"""
        selected = self.mount_tree.selection()
        if not selected:
            return
        item = self.mount_tree.item(selected[0])
        values = item["values"]
        if len(values) < 5:
            return

        # 获取双击的列
        region = self.mount_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col_id = self.mount_tree.identify_column(event.x)
        col_idx = int(col_id.replace("#", "")) - 1

        mount_dir = values[1]
        image_file = values[2]

        if col_idx == 2:  # 双击映像文件列
            self.image_file.set(image_file)
            self._load_info()
        elif col_idx == 1:  # 双击挂载目录列
            if os.path.exists(mount_dir):
                os.startfile(mount_dir)
            else:
                messagebox.showwarning("提示", f"目录不存在: {mount_dir}", parent=self.parent.master)

    def _browse_image(self):
        f = filedialog.askopenfilename(filetypes=[("映像", "*.wim *.esd *.swm"), ("所有", "*.*")])
        if f:
            self.image_file.set(f)
            self._load_info()

    def _auto_search_wim(self):
        """自动搜索WIM文件"""
        filepath = search_file(
            self.parent.master,
            icon_path=self.icon_path,
            title="搜索WIM文件",
            file_types={'.wim': 'WIM文件', '.esd': 'ESD文件', '.swm': 'SWM文件'},
            default_drives=['D:\\'],
            default_depth=3
        )
        
        if filepath:
            self.image_file.set(filepath)
            self._load_info()


    def _decode(self, data):
        if isinstance(data, bytes):
            for enc in ['gbk', 'utf-8', 'gb2312', 'cp936', 'latin-1']:
                try:
                    return data.decode(enc)
                except:
                    continue
            return data.decode('gbk', errors='replace')
        return str(data)

    def _is_progress_line(self, line):
        """判断是否是 DISM 进度行，如 '[===========50.0%===========]'"""
        if not line:
            return False
        stripped = line.strip()
        if stripped.startswith("[") and "%" in stripped:
            return True
        return False

    def _parse_progress(self, line):
        """从进度行中提取百分比数值"""
        import re
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        if m:
            try:
                return float(m.group(1))
            except:
                pass
        return -1

    def _log_filtered(self, line, progress_state, module="system"):
        """过滤式日志输出。DISM 进度行以 DEBUG 级别输出（默认不显示），其他行以 WARNING 级输出。

        progress_state: dict，用于跟踪上次输出的进度值
        """
        if self._is_progress_line(line):
            pct = self._parse_progress(line)
            if pct < 0:
                return
            # 每 10% 才输出一次到日志
            bucket = int(pct // 10) * 10
            if bucket <= progress_state.get("last_pct", -1):
                return
            progress_state["last_pct"] = bucket
            # 进度信息走 DEBUG 级别，默认配置下不刷屏
            logger_utils.log_debug(module, line)
        else:
            # 普通输出走 WARNING 级别
            logger_utils.log_warning(module, line)

    def _log_safe_filtered(self, line, progress_state, module="system"):
        """线程安全版本的过滤式日志输出"""
        if self._is_progress_line(line):
            pct = self._parse_progress(line)
            if pct < 0:
                return
            bucket = int(pct // 10) * 10
            if bucket <= progress_state.get("last_pct", -1):
                return
            progress_state["last_pct"] = bucket
            # 进度信息：DEBUG 级（默认不显示）
            logger_utils.log_debug(module, line)
        else:
            # 普通输出：WARNING 级
            logger_utils.log_warning(module, line)

    def _run(self, cmd, desc=""):
        self._log(desc)
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW, cwd=self.data_dir)
            raw = p.communicate()[0]
            out = self._decode(raw)
            progress_state = {}
            for line in out.split("\n"):
                line = line.strip()
                if line:
                    self._log_filtered(line, progress_state)
            return p.returncode == 0
        except Exception as e:
            self._log(f"错误: {e}")
            return False

    def _log_safe(self, msg):
        """线程安全的日志输出"""
        self._task_queue.put(("log", msg))

    def _status_safe(self, msg):
        """线程安全的状态更新"""
        self._task_queue.put(("status", msg))

    def _progress_safe(self, value, text=""):
        """线程安全的进度更新"""
        self._task_queue.put(("progress", value, text))

    def _done_safe(self, callback):
        """线程安全的完成回调"""
        self._task_queue.put(("done", callback))

    # ---------- 横幅通知（非阻塞，自动消失） ----------
    def _toast(self, msg, kind="info", duration_ms=2500):
        """统一横幅通知：优先路由到 wim_edit 的统一横幅；若无回调则退回到悬浮 Toplevel 横幅。
        默认显示时间 2.5 秒。

        kind: "info" (蓝色) / "success" (绿色) / "warning" (橙色) / "error" (红色)
        """
        # 优先使用统一横幅提醒
        if self._toast_callback:
            try:
                self._toast_callback(msg, kind, duration_ms)
                return
            except Exception:
                pass
        # 兜底：悬浮 Toplevel 横幅（独立运行时使用，不挤占布局、不下压进度条/状态栏）
        colors = {
            "info":    ("#3a86ff", "white"),
            "success": ("#2ec4b6", "white"),
            "warning": ("#ff9f1c", "black"),
            "error":   ("#e71d36", "white"),
        }
        bg, fg = colors.get(kind, colors["info"])

        if self._banner_window is None or not self._banner_window.winfo_exists():
            try:
                self._banner_window = tk.Toplevel(self.root)
            except Exception:
                return
            self._banner_window.overrideredirect(True)
            self._banner_window.attributes("-topmost", True)
            self._banner_window.attributes("-alpha", 0.95)
            self._banner_label = tk.Label(
                self._banner_window,
                text="",
                bg=bg,
                fg=fg,
                font=font_scaled("Microsoft YaHei", 10),
                anchor=tk.W,
                padx=px(10),
                pady=px(4),
            )
            self._banner_label.pack(fill=tk.BOTH, expand=True)

        self._banner_label.config(text=msg, bg=bg, fg=fg)

        try:
            self.root.update_idletasks()
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            root_w = self.root.winfo_width()
            root_h = self.root.winfo_height()
            margin_x = px(10)
            margin_y = px(4)
            bw = max(px(200), root_w - margin_x * 2)
            bh = self._banner_label.winfo_reqheight() + px(6)
            x = root_x + margin_x
            y = root_y + root_h - bh - margin_y - px(24)
            self._banner_window.geometry(f"{bw}x{bh}+{x}+{y}")
            self._banner_window.deiconify()
            try:
                self._banner_window.lift()
            except Exception:
                pass
        except Exception:
            pass

        # 若已有定时器在等，先取消
        if self._banner_after_id:
            try:
                self.root.after_cancel(self._banner_after_id)
            except Exception:
                pass
        self._banner_after_id = None

        def _hide():
            try:
                if self._banner_window is not None and self._banner_window.winfo_exists():
                    self._banner_window.withdraw()
            except Exception:
                pass
            self._banner_after_id = None

        self._banner_after_id = self.root.after(duration_ms, _hide)

    def _toast_safe(self, msg, kind="info", duration_ms=2500):
        """线程安全版本：后台线程通过队列调用主线程显示横幅"""
        self._task_queue.put(("toast", msg, kind, duration_ms))

    def _log_mod(self, module, level, msg):
        """通过 logger_utils 按模块/级别输出，同时兼容旧的 self._log"""
        # 旧日志回调仍然会被 logger_utils 触发
        # 这里也直接调一次保证老代码行为不变
        logger_utils.log(module, level, msg)

    def _log_err(self, module, msg):
        logger_utils.log_error(module, msg)

    def _log_warn(self, module, msg):
        logger_utils.log_warning(module, msg)

    def _log_debug(self, module, msg):
        logger_utils.log_debug(module, msg)

    def _run_get(self, cmd, desc=""):
        self._log_safe(desc)
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW, cwd=self.data_dir)
            raw = p.communicate()[0]
            out = self._decode(raw)
            progress_state = {}
            for line in out.split("\n"):
                line = line.strip()
                if line:
                    self._log_safe_filtered(line, progress_state)
            return p.returncode == 0, out
        except Exception as e:
            self._log_safe(f"错误: {e}")
            return False, ""

    def _run_async(self, work_fn, done_fn=None):
        """通用异步执行器：work_fn 在后台线程执行，完成后在主线程调用 done_fn(result)"""
        import threading
        def _worker():
            try:
                result = work_fn()
            except Exception as e:
                result = e
            if done_fn:
                self._done_safe(lambda: done_fn(result))
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _lock_buttons(self, locked):
        """挂载/卸载期间禁用按钮，避免重复操作"""
        if hasattr(self, 'btn_mount'):
            try:
                self.btn_mount.config(state=("disabled" if locked else "normal"))
            except Exception:
                pass
        if hasattr(self, 'btn_commit'):
            try:
                self.btn_commit.config(state=("disabled" if locked else "normal"))
            except Exception:
                pass
        if hasattr(self, 'btn_discard'):
            try:
                self.btn_discard.config(state=("disabled" if locked else "normal"))
            except Exception:
                pass
        if hasattr(self, 'btn_cleanup'):
            try:
                self.btn_cleanup.config(state=("disabled" if locked else "normal"))
            except Exception:
                pass

    def _run_get_silent(self, cmd, desc=""):
        """静默执行命令，只记录开始和结束，不逐行输出（用于耗时操作）"""
        self._log_safe(desc)
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW, cwd=self.data_dir)
            raw = p.communicate()[0]
            out = self._decode(raw)
            return p.returncode == 0, out
        except Exception as e:
            self._log_safe(f"错误: {e}")
            return False, ""

    def _load_info(self):
        img = self.image_file.get()
        if not img or not os.path.exists(img):
            messagebox.showerror("错误", "请选择映像文件", parent=self.parent.master)
            return
        self._set_progress(20, "正在加载信息...")
        ok, out = self._run_get([self.wimlib_exe, "info", img], "加载信息")
        if ok:
            self._parse_image_info(out)
            self._set_progress(100, "加载完成")
            self.root.after(500, self._clear_progress)
            self._set_status(f"已加载: {os.path.basename(img)}")
        else:
            self._clear_progress()

    def _parse_image_info(self, output):
        self.image_info = []
        images = []
        current = {}
        in_images_section = False

        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue

            if line.startswith("Available Images:"):
                in_images_section = True
                continue

            if in_images_section:
                if line.startswith("Index:"):
                    if current:
                        images.append(current)
                    current = {}
                    val = line.split(":", 1)[1].strip()
                    current["Index"] = val
                    self.image_info.append(("Index", val))
                elif ":" in line and current is not None:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip()
                        if key and val:
                            current[key] = val
                            self.image_info.append((key, val))
                elif line.startswith("---"):
                    continue
            else:
                if line.startswith("Image Count:"):
                    val = line.split(":", 1)[1].strip()
                    self.image_info.append(("Image Count", val))
                elif line.startswith("Boot Index:"):
                    val = line.split(":", 1)[1].strip()
                    self.image_info.append(("Boot Index", val))
                elif line.startswith("Size:"):
                    val = line.split(":", 1)[1].strip()
                    self.image_info.append(("Size", val))
                elif line.startswith("Compression:"):
                    val = line.split(":", 1)[1].strip()
                    self.image_info.append(("Compression", val))

        if current:
            images.append(current)

        # 填充索引下拉框
        idx_values = []
        for img in images:
            idx = img.get("Index", "")
            name = img.get("Display Name", "") or img.get("Name", "")
            if idx:
                idx_values.append(f"{idx} {name}")
        self.idx_combo["values"] = idx_values
        if idx_values:
            self.idx_combo.current(0)

        # 填充当前选中索引的信息
        if images:
            img = images[0]
            self.display_name.set(img.get("Display Name", "") or img.get("Name", ""))
            self.display_desc.set(img.get("Display Description", "") or img.get("Description", ""))
            self.image_name.set(img.get("Name", ""))
            self.image_desc.set(img.get("Description", ""))

            arch = img.get("Architecture", "")
            version = f"{img.get('Major Version', '')}.{img.get('Minor Version', '')}" if img.get("Major Version") else ""
            lang = img.get("Languages", "")

            self.idx_arch.config(text=f"[{arch}]" if arch else "")
            self.idx_version.config(text=version if version else "")

            other_parts = []
            if lang:
                other_parts.append(f"语言:({lang})")
            edition = img.get("Edition ID", "") or img.get("Flags", "")
            if edition:
                other_parts.append(f"版本:{edition}")
            build = img.get("Build", "")
            if build:
                other_parts.append(f"Build:{build}")
            self.other_info.set("  ".join(other_parts))

    def _is_admin(self):
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False

    def _add_mount_entry(self, idx, mnt, img):
        entry = {
            "idx": str(len(self.mount_list) + 1),
            "mount_dir": mnt,
            "image_file": img,
            "index": idx,
            "status": "正常"
        }
        self.mount_list.append(entry)
        self.mount_tree.insert("", tk.END, values=(
            entry["idx"], entry["mount_dir"], entry["image_file"],
            entry["index"], entry["status"]
        ))

    def _remove_mount_entry(self, mnt):
        # 记录当前顶部显示的映像文件路径，避免卸载后被清空，
        # 以便用户可继续点击「镜像优化」/「信息处理」
        saved_image_file = self.image_file.get()
        saved_img_index = self.img_index.get()

        for i, entry in enumerate(self.mount_list):
            if entry["mount_dir"] == mnt:
                self.mount_list.pop(i)
                break
        for item in self.mount_tree.get_children():
            self.mount_tree.delete(item)
        for i, entry in enumerate(self.mount_list):
            entry["idx"] = str(i + 1)
            self.mount_tree.insert("", tk.END, values=(
                entry["idx"], entry["mount_dir"], entry["image_file"],
                entry["index"], entry["status"]
            ))

        # 恢复顶部映像文件路径（如果之前有值的话）
        if saved_image_file:
            self.image_file.set(saved_image_file)
        if saved_img_index:
            self.img_index.set(saved_img_index)

    def _force_remove_dir(self, mnt):
        """多策略强制删除目录：先清属性，再尝试 os/shutil，最后回退到 cmd rmdir /S/Q。
        多轮重试 + 短延迟，用于对抗 Explorer 句柄/防病毒文件锁/只读属性。"""
        if not mnt or not isinstance(mnt, str):
            return False
        if not os.path.exists(mnt):
            return True

        def _strip_readonly(path):
            """递归清除只读/隐藏/系统属性（通过 attrib 命令，最稳）"""
            try:
                subprocess.Popen(
                    ["attrib", "-R", "-H", "-S", "/S", "/D", os.path.join(path, "*")],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW
                ).communicate(timeout=15)
            except Exception:
                pass
            # 同时走 Python 路径，确保顶层目录也能清除
            try:
                for root, dirs, files in os.walk(path):
                    for f in files + dirs:
                        fp = os.path.join(root, f)
                        try:
                            os.chmod(fp, 0o777)
                        except Exception:
                            pass
            except Exception:
                pass

        def _try_delete_once():
            if not os.path.exists(mnt):
                return True
            _strip_readonly(mnt)
            # 1) 优先 os.rmdir / shutil.rmtree
            try:
                entries = os.listdir(mnt)
                if not entries:
                    os.rmdir(mnt)
                else:
                    import shutil
                    shutil.rmtree(mnt, ignore_errors=False)
            except Exception:
                # 2) shutil 失败时，回退到 cmd 原生 rmdir /S /Q
                #    cmd 的内部句柄处理比 shutil 对 Windows 上的文件锁更宽容
                try:
                    p = subprocess.Popen(
                        ["cmd", "/C", "rmdir", "/S", "/Q", mnt],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    p.communicate(timeout=30)
                except Exception:
                    pass
            return not os.path.exists(mnt)

        # 多轮重试（每轮之间稍作等待，给 Explorer/杀毒释放句柄的时间）
        max_attempts = 4
        for attempt in range(max_attempts):
            if _try_delete_once():
                return True
            import time
            try:
                time.sleep(0.5 + attempt * 0.3)
            except Exception:
                pass
        # 最终再试一次 shutil（忽略错误，尽量清理）
        try:
            import shutil
            shutil.rmtree(mnt, ignore_errors=True)
        except Exception:
            pass
        return not os.path.exists(mnt)

    def _remove_mount_dir(self, mnt):
        """卸载后自动删除挂载目录（含安全检查）"""
        if not mnt or not isinstance(mnt, str):
            return
        mnt = self._normalize_path(mnt)
        # 安全检查：禁止删除系统根目录
        if not self._is_safe_mount_dir(mnt):
            self._log_safe(f"安全检查阻止删除: {mnt}")
            return
        # 额外检查：目录必须是我们创建的挂载点（包含 '_WIM_Mount' 或较小且不含系统文件）
        if "_WIM_Mount" not in mnt and os.path.exists(mnt):
            try:
                entries = os.listdir(mnt)
                system_dirs = ["Windows", "Program Files", "ProgramData", "Users", "$Recycle.Bin"]
                for entry in entries:
                    if entry in system_dirs:
                        self._log_safe(f"疑似系统目录，拒绝删除: {mnt}")
                        return
            except Exception:
                pass
        try:
            if not os.path.exists(mnt):
                return
            # 先尝试使用多策略强制删除
            ok = self._force_remove_dir(mnt)
            # 清理父目录 D:\_WIM_Mount（如果已经空）
            try:
                parent = os.path.dirname(mnt)
                if parent and "_WIM_Mount" in os.path.basename(parent):
                    if os.path.exists(parent) and os.path.isdir(parent):
                        try:
                            entries = os.listdir(parent)
                            if not entries:
                                os.chmod(parent, 0o777)
                                os.rmdir(parent)
                        except Exception:
                            pass
            except Exception:
                pass
            if ok:
                self._log_safe(f"已清理挂载目录: {mnt}")
            else:
                self._log_safe(f"目录仍无法删除（可能被资源管理器/防病毒占用）: {mnt}")
        except Exception as e:
            self._log_safe(f"删除目录失败: {e}")

    def _on_mount_select(self, event):
        selected = self.mount_tree.selection()
        if not selected:
            return
        item = self.mount_tree.item(selected[0])
        values = item["values"]
        if len(values) >= 4:
            self.image_file.set(values[2])
            self.img_index.set(values[3])
            self._set_status(f"已选择: {values[1]}")

    def _normalize_path(self, path):
        if not path or not isinstance(path, str):
            return ""
        return os.path.normpath(path).replace("/", "\\")

    def _get_dism_exe(self):
        """获取最可靠的 DISM 路径。优先使用系统 DISM，失败回退到捆绑 DISM。"""
        system_dism = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "Dism.exe")
        if os.path.exists(system_dism):
            return system_dism
        return self.dism_exe

    def _cleanup_stale_mount(self, mnt):
        """清理残留挂载。线程安全（也可在后台线程调用）。

        策略（覆盖最多故障场景）：
          1) 先尝试 /Unmount-Wim /Commit（如果用户有变更需要写回，优先保留）
          2) 再尝试 /Unmount-Wim /Discard（放弃变更也能释放）
          3) 最后用 /Cleanup-Wim 作为兜底，清除 DISM 注册表中损坏的挂载状态"""
        if not mnt or not isinstance(mnt, str):
            return
        mnt = self._normalize_path(mnt)
        if not self._is_safe_mount_dir(mnt):
            self._log_safe(f"安全检查阻止清理: {mnt}")
            return
        dism = self._get_dism_exe()
        self._log_safe(f"清理残留挂载: {mnt}")
        ok = False
        ok, _ = self._run_get([dism, "/Unmount-Wim", f"/MountDir:{mnt}", "/Commit"], "保存卸载(清理)")
        if not ok:
            ok, _ = self._run_get([dism, "/Unmount-Wim", f"/MountDir:{mnt}", "/Discard"], "放弃卸载(清理)")
        if not ok:
            # /Cleanup-Wim 能强制清理所有损坏的挂载状态（日志证明此方法有效）
            self._run([dism, "/Cleanup-Wim"], "DISM-Cleanup-Wim")
        self._remove_mount_dir(mnt)

    def _is_safe_mount_dir(self, mnt):
        """安全检查：挂载目录不能是系统根目录或已有重要文件的目录"""
        if not mnt or not isinstance(mnt, str):
            return False
        mnt_norm = os.path.normpath(os.path.abspath(mnt)).strip()
        # 禁止挂载到系统根目录
        forbidden_roots = [
            "C:\\", "D:\\", "E:\\", "F:\\",
            "C:/", "D:/", "E:/", "F:/",
            "C:", "D:", "E:", "F:",
            os.environ.get("SystemRoot", "C:\\Windows"),
        ]
        for fr in forbidden_roots:
            try:
                if os.path.normpath(os.path.abspath(fr)).strip() == mnt_norm:
                    return False
            except:
                continue
        # 禁止挂载到 '.' 或空路径
        if mnt_norm in (".", "..") or len(mnt_norm) <= 3:
            return False
        # 检查是否是已存在的系统重要目录
        # 如果是我们自己的挂载目录（包含 _WIM_Mount），跳过此检查
        # （因为 BOOT.wim 等 Windows PE 镜像内部本身就有 Windows 目录，是正常情况）
        if "_WIM_Mount" not in mnt_norm:
            system_dirs = ["Windows", "Program Files", "ProgramData", "Users", "$Recycle.Bin"]
            if os.path.exists(mnt_norm) and os.path.isdir(mnt_norm):
                try:
                    entries = os.listdir(mnt_norm)
                    # 如果目录包含系统标志性目录，认为不安全
                    for entry in entries:
                        if entry in system_dirs:
                            return False
                except:
                    pass
        return True

    def _is_safe_image_file(self, img):
        """安全检查：确认是有效的WIM镜像文件"""
        if not img or not isinstance(img, str):
            return False
        img_norm = os.path.normpath(os.path.abspath(img)).strip()
        if not os.path.exists(img_norm):
            return False
        if not os.path.isfile(img_norm):
            return False
        # 检查扩展名
        if not img_norm.lower().endswith(('.wim', '.esd', '.swm')):
            return False
        # 检查文件大小至少 > 1MB（过小可能不是有效镜像）
        try:
            size = os.path.getsize(img_norm)
            if size < 1024 * 1024:
                return False
        except:
            pass
        return True

    def _mount(self):
        # ---------- 前置检查（主线程） ----------
        img_raw = self.image_file.get()
        if not img_raw or not img_raw.strip():
            messagebox.showerror("错误", "请先选择WIM文件", parent=self.parent.master)
            return
        img = self._normalize_path(img_raw.strip())
        if not self._is_safe_image_file(img):
            messagebox.showerror("错误", f"无效的WIM文件:\n{img}\n\n请通过浏览或搜索功能选择有效的 .wim/.esd/.swm 文件", parent=self.parent.master)
            return
        if not self._is_admin():
            messagebox.showerror("错误", "请以管理员身份运行此程序！\n\nDISM 挂载操作需要管理员权限。", parent=self.parent.master)
            return
        idx_raw = self.img_index.get() or "1"
        idx = idx_raw.split()[0] if idx_raw else "1"
        img_basename = os.path.basename(img)
        if not img_basename or img_basename in (".", ".."):
            messagebox.showerror("错误", f"无效的文件路径: {img}", parent=self.parent.master)
            return
        img_name = os.path.splitext(img_basename)[0]
        if not img_name:
            messagebox.showerror("错误", f"无法从文件名提取目录名: {img}", parent=self.parent.master)
            return
        mnt = os.path.join("D:\\", "_WIM_Mount", img_name)
        if not self._is_safe_mount_dir(mnt):
            messagebox.showerror("错误", f"不安全的挂载目录: {mnt}\n\n禁止挂载到系统根目录！", parent=self.parent.master)
            return
        # ---------- 耗时操作移到后台线程 ----------
        self._lock_buttons(True)
        self._set_progress(30, "正在准备...")
        self._log_safe(f"准备挂载到: {mnt}")

        dism_exe = self._get_dism_exe()
        mount_cmd = [dism_exe, "/Mount-Wim", f"/WimFile:{img}", f"/Index:{idx}", f"/MountDir:{mnt}"]
        mount_desc = f"挂载(索引{idx})"

        def _do_mount():
            # 1. 清理残留挂载 + 目录
            if os.path.exists(mnt):
                self._cleanup_stale_mount(mnt)
                if os.path.exists(mnt):
                    try:
                        if os.listdir(mnt):
                            self._log_safe(f"挂载目录仍非空，尝试删除: {mnt}")
                            import shutil
                            shutil.rmtree(mnt, ignore_errors=True)
                            if os.path.exists(mnt):
                                self._log_safe(f"警告: 目录未完全清理，仍存在: {mnt}")
                    except Exception as e:
                        self._log_safe(f"清理目录失败: {e}")
            try:
                os.makedirs(mnt, exist_ok=True)
            except Exception as e:
                return ("error", f"创建挂载目录失败: {mnt}\n错误: {e}")
            if not os.path.isdir(mnt) or not self._is_safe_mount_dir(mnt):
                return ("error", f"挂载目录验证失败: {mnt}")
            # 2. 执行挂载
            self._progress_safe(40, "正在挂载...")
            self._log_safe(f"执行命令: {' '.join(mount_cmd)}")
            ok, err = self._run_get(mount_cmd, mount_desc)
            return ("mount", ok, err, idx, mnt, img)

        def _done(result):
            self._lock_buttons(False)
            if isinstance(result, Exception):
                self._set_progress(0, "")
                self._set_status("执行失败")
                messagebox.showerror("错误", f"执行异常: {result}", parent=self.parent.master)
                return
            if result[0] == "error":
                self._set_progress(0, "")
                messagebox.showerror("错误", result[1], parent=self.parent.master)
                return
            tag, ok, err, idx_val, mnt_val, img_val = result
            if ok:
                self.temp_mount_dir = mnt_val
                self._add_mount_entry(idx_val, mnt_val, img_val)
                self._set_progress(100, "挂载成功")
                self._set_status(f"已挂载到: {mnt_val}")
                self._log_warn("mount", f"挂载成功: {mnt_val}")
                self._toast(f"✓ 挂载成功：{mnt_val}", "success", 2500)
            else:
                err_msg = "挂载失败"
                if err:
                    for line in err.split("\n"):
                        line = line.strip()
                        if line and ("error" in line.lower() or "fail" in line.lower() or "错误" in line or "拒绝" in line or "0x" in line):
                            err_msg += f"\n{line}"
                            break
                self._set_progress(0, "")
                self._set_status("挂载失败")
                try:
                    if os.path.isdir(mnt_val) and not os.listdir(mnt_val):
                        os.rmdir(mnt_val)
                        self._log_safe(f"已清理空目录: {mnt_val}")
                except:
                    pass
                messagebox.showerror("失败", err_msg, parent=self.parent.master)

        self._run_async(_do_mount, _done)

    def _unmount(self, commit=False):
        # ---------- 前置检查（主线程） ----------
        selected = self.mount_tree.selection()
        if selected:
            item = self.mount_tree.item(selected[0])
            mnt = item["values"][1]
        else:
            messagebox.showerror("错误", "请在挂载列表中选择要卸载的项", parent=self.parent.master)
            return
        if not mnt:
            messagebox.showerror("错误", "请选择挂载项", parent=self.parent.master)
            return
        if not self._is_admin():
            messagebox.showerror("错误", "请以管理员身份运行此程序！", parent=self.parent.master)
            return
        action = "保存卸载" if commit else "放弃卸载"
        # ---------- 耗时操作移到后台线程 ----------
        self._lock_buttons(True)
        self._set_progress(30, f"正在{action}...")
        dism_exe = self._get_dism_exe()

        def _do_unmount():
            ok = False
            if commit:
                # 两阶段：先 Commit 再 Unmount
                self._run_get([dism_exe, "/Commit-Wim", f"/MountDir:{mnt}"], "保存变更")
                ok, _ = self._run_get([dism_exe, "/Unmount-Wim", f"/MountDir:{mnt}", "/Discard"], "卸载目录")
                if not ok:
                    ok, _ = self._run_get([dism_exe, "/Unmount-Wim", f"/MountDir:{mnt}", "/Commit"], "保存卸载")
            else:
                ok, _ = self._run_get([dism_exe, "/Unmount-Wim", f"/MountDir:{mnt}", "/Discard"], "放弃卸载")
            return ("unmount", ok, commit, mnt)

        def _done(result):
            self._lock_buttons(False)
            if isinstance(result, Exception):
                self._set_progress(0, "")
                self._set_status("执行失败")
                messagebox.showerror("错误", f"执行异常: {result}", parent=self.parent.master)
                return
            tag, ok, commit_val, mnt_val = result
            action_val = "保存卸载" if commit_val else "放弃卸载"
            if ok:
                self._remove_mount_entry(mnt_val)
                self._remove_mount_dir(mnt_val)
                self._set_progress(100, f"{action_val}成功")
                self._set_status(f"{action_val}成功")
                self._log_warn("unmount", f"{action_val}成功: {mnt_val}")
                if commit_val:
                    self._toast("✓ 保存卸载成功，可点击「镜像优化」", "success", 2500)
                else:
                    self._toast(f"✓ {action_val}成功", "success", 2500)
            else:
                self._log_warn("unmount", f"卸载失败，强制清理: {mnt_val}")
                self._cleanup_stale_mount(mnt_val)
                self._remove_mount_entry(mnt_val)
                self._set_progress(0, "")
                self._set_status("已清理残留挂载")
                self._toast("⚠ 已清理残留挂载点，请重新尝试挂载", "warning", 2500)

        self._run_async(_do_unmount, _done)

    def _cleanup_all(self):
        # ---------- 前置检查（主线程） ----------
        if not self._is_admin():
            messagebox.showerror("错误", "请以管理员身份运行此程序！", parent=self.parent.master)
            return
        self._lock_buttons(True)
        self._set_progress(10, "正在获取挂载信息...")
        dism_exe = self._get_dism_exe()

        def _do_cleanup():
            ok, out = self._run_get([dism_exe, "/Get-MountedWimInfo"], "获取挂载信息")
            if not ok:
                return ("error", "无法获取挂载信息")
            mount_dirs = []
            if out:
                for line in out.split("\n"):
                    line = line.strip()
                    if "安装目录" in line or "Mount Dir" in line or "挂载目录" in line:
                        dir_path = line.split(":", 1)[1].strip() if ":" in line else ""
                        if dir_path:
                            mount_dirs.append(dir_path)
            if mount_dirs:
                self._log_safe(f"发现 {len(mount_dirs)} 个挂载点，开始清理")
                for i, mnt in enumerate(mount_dirs):
                    self._progress_safe(20 + int(80 * (i + 1) / len(mount_dirs)), f"清理 {i+1}/{len(mount_dirs)}...")
                    self._cleanup_stale_mount(mnt)
                return ("ok", mount_dirs)
            return ("empty", [])

        def _done(result):
            self._lock_buttons(False)
            if isinstance(result, Exception):
                self._set_progress(0, "")
                self._set_status("执行失败")
                messagebox.showerror("错误", f"执行异常: {result}", parent=self.parent.master)
                return
            tag = result[0]
            if tag == "error":
                self._set_progress(0, "")
                self._set_status("获取挂载信息失败")
                messagebox.showerror("失败", result[1], parent=self.parent.master)
                return
            if tag == "ok":
                dirs = result[1]
                self._set_progress(100, "清理完成")
                self._set_status("清理完成")
                self._toast(f"✓ 已清理 {len(dirs)} 个挂载点", "success", 1800)
            else:
                self._set_progress(0, "")
                self._set_status("没有残留挂载")
                self._toast("没有发现残留挂载点", "info", 1500)

        self._run_async(_do_cleanup, _done)

    def _optimize(self):
        img = self._normalize_path(self.image_file.get())
        if not img or not os.path.exists(img):
            messagebox.showerror("错误", "请选择文件", parent=self.parent.master)
            return
        self._progress_safe(20, "正在优化...")
        self._status_safe("正在优化...")
        # 使用后台线程执行优化，避免阻塞UI
        def _do_optimize():
            # 使用静默模式，不逐行输出日志，避免事件队列积压
            ok, out = self._run_get_silent([self.wimlib_exe, "optimize", img], "优化")
            # 回到主线程更新UI
            self._done_safe(lambda: self._optimize_done(ok, out))
        threading.Thread(target=_do_optimize, daemon=True).start()

    def _optimize_done(self, ok, out):
        """优化完成回调"""
        if ok:
            self._progress_safe(100, "优化完成")
            self._status_safe("优化完成")
            self._log_warn("optimize", "优化完成")
            self._toast_safe("✓ 优化完成", "success", 1500)
        else:
            self._status_safe("优化失败")
            self._log_err("optimize", "优化失败")
            if out:
                self._log_debug("optimize", out)
            messagebox.showerror("失败", "优化失败", parent=self.parent.master)

    def _on_idx_change(self, event=None):
        sel = self.idx_combo.get()
        if not sel:
            return
        idx = sel.split()[0] if sel else "1"
        self.img_index.set(idx)
        img = self.image_file.get()
        if not img or not os.path.exists(img):
            return
        ok, out = self._run_get([self.wimlib_exe, "info", img, idx], f"加载索引{idx}")
        if ok:
            images = []
            current = {}
            current_section = ""
            for line in out.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("["):
                    if current:
                        images.append(current)
                    current = {"section": line}
                    current_section = line
                elif ":" in line and current_section:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip()
                        if key and val:
                            current[key] = val
            if current:
                images.append(current)
            if images:
                img_data = images[0]
                self.display_name.set(img_data.get("Display Name", "") or img_data.get("Name", ""))
                self.display_desc.set(img_data.get("Display Description", "") or img_data.get("Description", ""))
                self.image_name.set(img_data.get("Name", ""))
                self.image_desc.set(img_data.get("Description", ""))
                arch = img_data.get("Architecture", "")
                version = f"{img_data.get('Major Version', '')}.{img_data.get('Minor Version', '')}" if img_data.get("Major Version") else ""
                lang = img_data.get("Languages", "")
                self.idx_arch.config(text=f"[{arch}]" if arch else "")
                self.idx_version.config(text=version if version else "")
                other_parts = []
                if lang:
                    other_parts.append(f"语言:({lang})")
                edition = img_data.get("Edition ID", "") or img_data.get("Flags", "")
                if edition:
                    other_parts.append(f"版本:{edition}")
                build = img_data.get("Build", "")
                if build:
                    other_parts.append(f"Build:{build}")
                self.other_info.set("  ".join(other_parts))

    def _enable_edit(self):
        img = self.image_file.get()
        if not img or not os.path.exists(img):
            messagebox.showerror("错误", "请先选择映像文件", parent=self.parent.master)
            return
        self.edit_mode = True
        self.edit_backup = {
            "display_name": self.display_name.get(),
            "display_desc": self.display_desc.get(),
            "image_name": self.image_name.get(),
            "image_desc": self.image_desc.get(),
        }
        self.display_name_entry.config(state="normal")
        self.display_desc_entry.config(state="normal")
        self.image_name_entry.config(state="normal")
        self.image_desc_entry.config(state="normal")
        self.display_name_entry.focus_set()
        self._set_status("已进入编辑模式，修改后点击确定保存")

    def _cancel_edit(self):
        if self.edit_mode:
            self.display_name.set(self.edit_backup.get("display_name", ""))
            self.display_desc.set(self.edit_backup.get("display_desc", ""))
            self.image_name.set(self.edit_backup.get("image_name", ""))
            self.image_desc.set(self.edit_backup.get("image_desc", ""))
            self.edit_mode = False
            self.edit_backup = {}
        self.display_name_entry.config(state="readonly")
        self.display_desc_entry.config(state="readonly")
        self.image_name_entry.config(state="readonly")
        self.image_desc_entry.config(state="readonly")
        self._set_status("已取消编辑")

    def _save_info_changes(self):
        img = self.image_file.get()
        if not img or not os.path.exists(img):
            messagebox.showerror("错误", "请先选择映像文件", parent=self.parent.master)
            return
        if not self.edit_mode:
            messagebox.showinfo("提示", "请先点击信息处理进入编辑模式", parent=self.parent.master)
            return
        idx = self.img_index.get().split()[0] if self.img_index.get() else "1"
        display_name = self.display_name.get().strip()
        display_desc = self.display_desc.get().strip()
        image_name = self.image_name.get().strip()
        image_desc = self.image_desc.get().strip()
        if not display_name and not display_desc and not image_name and not image_desc:
            messagebox.showinfo("提示", "没有可保存的修改", parent=self.parent.master)
            return
        if messagebox.askyesno("确认", "确定要保存镜像信息修改?", parent=self.parent.master):
            self._set_progress(20, "正在保存...")
            ok = True
            # 修改显示名称/描述（使用 --image-property）
            if display_name:
                cmd = [self.wimlib_exe, "info", img, idx, "--image-property", f"DISPLAYNAME={display_name}"]
                if not self._run(cmd, f"修改显示名称:{display_name}"):
                    ok = False
            if display_desc and ok:
                cmd = [self.wimlib_exe, "info", img, idx, "--image-property", f"DISPLAYDESCRIPTION={display_desc}"]
                if not self._run(cmd, f"修改显示描述:{display_desc}"):
                    ok = False
            # 修改镜像名称/描述（合并为一次命令，避免空字符串覆盖）
            if (image_name or image_desc) and ok:
                # 获取当前值作为默认值
                cur_name = self.edit_backup.get("image_name", "")
                cur_desc = self.edit_backup.get("image_desc", "")
                final_name = image_name if image_name else cur_name
                final_desc = image_desc if image_desc else cur_desc
                cmd = [self.wimlib_exe, "info", img, idx, final_name, final_desc]
                if not self._run(cmd, f"修改镜像信息: 名称={final_name}, 描述={final_desc}"):
                    ok = False
            if ok:
                self._set_progress(100, "信息保存完成")
                self._set_status("信息保存完成")
                self._log_warn("info", "信息保存完成")
                self._toast("✓ 信息保存完成", "success", 1500)
            else:
                self._clear_progress()
                self._set_status("保存失败")
                self._log_err("info", "保存失败，请查看日志")
                messagebox.showerror("错误", "保存失败，请查看日志", parent=self.parent.master)
                return
            self.edit_mode = False
            self.edit_backup = {}
            self.display_name_entry.config(state="readonly")
            self.display_desc_entry.config(state="readonly")
            self.image_name_entry.config(state="readonly")
            self.image_desc_entry.config(state="readonly")
            self._load_info()

    def _clear_selection(self):
        self.image_file.set("")
        self.display_name.set("")
        self.display_desc.set("")
        self.image_name.set("")
        self.image_desc.set("")
        self.other_info.set("")
        self.idx_combo["values"] = []
        self.idx_arch.config(text="")
        self.idx_version.config(text="")
        self.edit_mode = False
        self.edit_backup = {}
        self.display_name_entry.config(state="readonly")
        self.display_desc_entry.config(state="readonly")
        self.image_name_entry.config(state="readonly")
        self.image_desc_entry.config(state="readonly")
        self._set_status("已清除")