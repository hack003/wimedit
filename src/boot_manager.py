# -*- coding: utf-8 -*-
"""引导管理模块 - BCD管理、引导修复"""

import os
import re
import shutil
import string
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from boot_utils import BootEnvironmentDetector
from boot_add_menu import BootAddMenu
from dpi_utils import px, font_scaled, dpi_geometry


# bcdedit 输出中有效的引导项类型标题
_BOOT_SECTION_TITLES = (
    "Windows Boot Loader",
    "Windows Boot Manager",
    "Firmware Boot Manager",
    "Windows 启动加载器",
    "Windows 启动管理器",
    "固件启动管理器",
)

# bcdedit 输出中所有节标题（包括非启动加载器类型）
_ALL_BOOT_SECTION_TITLES = (
    "Windows Boot Loader",
    "Resume from Hibernate",
    "Windows Memory Tester",
    "Windows Boot Manager",
    "Firmware Boot Manager",
    "EMS Settings",
    "Debugger Settings",
    "RAM Defects",
    "Global Settings",
    "Boot Loader Settings",
    "Hypervisor Settings",
    "Resume Loader Settings",
    "Device options",
    "Setup Ramdisk Options",
    "Windows 启动加载器",
    "Windows 启动管理器",
    "固件启动管理器",
)

# bcdedit 输出中的属性名称（中英文）
_PROP_IDENTIFIER = ("identifier", "标识符")
_PROP_DESCRIPTION = ("description", "描述")

_GUID_RE = re.compile(r'\{[0-9a-fA-F-]+\}')
_BOOT_SECTION_TITLES_RE = re.compile(
    '|'.join(re.escape(t) for t in _ALL_BOOT_SECTION_TITLES)
)
_BOOT_LOADER_RE = re.compile(
    '|'.join(re.escape(t) for t in ("Windows Boot Loader", "Windows 启动加载器"))
)


class BootManager:
    def __init__(self, parent, root, base_dir, data_dir, wimlib_exe, dism_exe, sevenz_exe,
                 log_callback, status_callback, progress_callback, tab_frame=None, icon_path=None,
                 boot_env_cache=None, boot_detector=None):
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
        self._clear_progress = lambda: progress_callback(0, "")
        self._boot_env_cache = boot_env_cache
        self.bcd_entries = []
        self.show_all_bcd = False
        self._refresh_busy = False      # 刷新进行中标记，防止重复点击
        self._refresh_buttons = []      # 需要在刷新期间禁用的按钮
        self._boot_drive = None         # 缓存引导分区盘符（如 "Z"）
        self._sys_drive = None          # 缓存系统分区盘符（如 "C"）
        self._is_uefi = None            # 缓存目标引导模式（True=UEFI, False=BIOS）

        # 使用传入的 boot_detector 实例，或创建新的（兼容旧代码）
        self.boot_detector = boot_detector if boot_detector else BootEnvironmentDetector(log_callback)

        # 标记是否已自动加载过BCD（避免每次切换都刷新）
        self._bcd_auto_loaded = False

        if tab_frame is not None:
            self.parent = tab_frame
        else:
            self.parent = ttk.Frame(parent)
            parent.add(self.parent, text="引导管理")

        # 创建添加引导菜单实例（必须在 self.parent 赋值之后）
        self.boot_add_menu = BootAddMenu(self)

        self._build_ui()

    # ------------------------------------------------------------------
    # 工具方法：委托给 boot_detector
    # ------------------------------------------------------------------
    def _decode(self, data):
        return self.boot_detector.decode(data)

    def _run(self, cmd, desc=""):
        return self.boot_detector.run(cmd, desc)

    def _run_get(self, cmd, desc=""):
        return self.boot_detector.run_get(cmd, desc)

    def _is_admin(self):
        return self.boot_detector.is_admin()

    def _get_bcd_args(self, force_mount=False):
        return self.boot_detector.get_bcd_args(force_mount)

    def _ensure_efi_mounted(self, boot_env=None):
        return self.boot_detector.ensure_efi_mounted(boot_env)

    def _detect_boot_environment(self):
        if self._boot_env_cache is not None:
            self._log("使用已缓存的引导环境检测结果", update_status=False)
            return self._boot_env_cache
        return self.boot_detector.detect_boot_environment()

    def _check_efi_partition(self, drive_letter):
        return self.boot_detector.check_efi_partition(drive_letter)

    def _find_offline_system_drive(self):
        return self.boot_detector.find_offline_system_drive()

    def _read_offline_registry(self, drive, value_name):
        return self.boot_detector.read_offline_registry(drive, value_name)

    def _mount_efi_partition(self, preferred_letter=None):
        return self.boot_detector.ensure_efi_mounted()

    def _ensure_ramdisk_options(self):
        return self.boot_detector.ensure_ramdisk_options(self.base_dir, self.data_dir)

    # ------------------------------------------------------------------
    # 辅助工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_property_value(line):
        """解析 'identifier              {guid}' 形式的属性行，返回值字符串或空"""
        parts = line.split(None, 1)
        return parts[1].strip() if len(parts) > 1 else ""

    @staticmethod
    def _extract_guid(text):
        """从文本中提取形如 {xxxx-...-xxxx} 的 GUID"""
        m = _GUID_RE.search(text)
        return m.group(0) if m else ""

    @staticmethod
    def _split_drive_abs(path):
        """将绝对路径拆分为 (盘符, 带反斜杠前缀的相对路径)，例如 'C:\\test.wim' -> ('C:', '\\test.wim')"""
        drive, rel = os.path.splitdrive(os.path.normpath(path))
        if not rel.startswith("\\"):
            rel = "\\" + rel
        return drive, rel

    def _create_dialog(self, title, size="400x200"):
        """创建具有公共属性的对话框 Toplevel"""
        dialog = tk.Toplevel(self.parent.master)
        dialog.title(title)
        parts = size.split("x")
        dialog.geometry(dpi_geometry(int(parts[0]), int(parts[1])))
        dialog.transient(self.parent.master)
        dialog.grab_set()
        if self.icon_path and os.path.exists(self.icon_path):
            for _i in range(5):
                try:
                    dialog.iconbitmap(self.icon_path)
                    break
                except Exception:
                    import time
                    time.sleep(1)
        return dialog

    def _build_ui(self):
        main_frame = ttk.Frame(self.parent, padding=px(3))
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 顶部：引导项下拉选择
        top_frame = ttk.LabelFrame(main_frame, text="引导项选择", padding=px(3))
        top_frame.pack(fill=tk.X, pady=(0, px(3)))

        ttk.Label(top_frame, text="引导项:").pack(side=tk.LEFT, padx=(0, px(5)))
        self.bcd_combo = ttk.Combobox(top_frame, state="readonly", width=50)
        self.bcd_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, px(5)))
        self.bcd_combo.bind("<<ComboboxSelected>>", self._on_bcd_combo_select)

        self.refresh_btn_top = ttk.Button(top_frame, text="刷新", command=self._refresh_bcd_list, width=8)
        self.refresh_btn_top.pack(side=tk.LEFT, padx=px(2))
        self._refresh_buttons.append(self.refresh_btn_top)

        # 属性值区域（初始紧凑高度 = 7行，窗口拉大时再扩展）
        right_frame = ttk.LabelFrame(main_frame, text="属性值", padding=px(3))
        right_frame.pack(fill=tk.BOTH, expand=True, pady=(0, px(3)))

        prop_columns = ("property", "value")
        self.bcd_prop_tree = ttk.Treeview(
            right_frame, columns=prop_columns, show="headings",
            height=7,
        )
        self.bcd_prop_tree.heading("property", text="属性名")
        self.bcd_prop_tree.heading("value", text="值")
        self.bcd_prop_tree.column("property", width=px(150), anchor=tk.W)
        self.bcd_prop_tree.column("value", width=px(300), anchor=tk.W)

        prop_scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.bcd_prop_tree.yview)
        self.bcd_prop_tree.configure(yscrollcommand=prop_scrollbar.set)

        self.bcd_prop_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        prop_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.bcd_prop_tree.bind("<Double-1>", self._on_prop_edit)
        self.bcd_prop_tree.bind("<Button-3>", self._on_prop_right_click)
        self.bcd_prop_tree.bind("<Configure>", self._on_prop_tree_resize)

        bcd_btn_frame = ttk.Frame(main_frame)
        bcd_btn_frame.pack(fill=tk.X, pady=(px(3), 0))

        ttk.Button(bcd_btn_frame, text="删除", command=self._bcd_delete_dialog, width=8).pack(side=tk.LEFT, padx=px(2))
        ttk.Button(bcd_btn_frame, text="设为默认", command=self._bcd_set_default, width=8).pack(side=tk.LEFT, padx=px(2))

        ttk.Separator(bcd_btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=px(5))

        self.filter_btn = ttk.Button(bcd_btn_frame, text="全部", command=self._toggle_bcd_filter, width=8)
        self.filter_btn.pack(side=tk.LEFT, padx=px(2))
        self.reset_btn = ttk.Button(bcd_btn_frame, text="重置", command=self._reset_boot, width=8)
        self.reset_btn.pack(side=tk.LEFT, padx=px(2))
        self._set_tooltip(self.reset_btn, "备份并清空损坏BCD引导配置，清除无效启动条目，仅清理配置不生成引导")
        self.repair_full_btn = ttk.Button(bcd_btn_frame, text="修复引导", command=self._repair_boot_full, width=8)
        self.repair_full_btn.pack(side=tk.LEFT, padx=px(2))
        self._set_tooltip(self.repair_full_btn, "完整重装全套EFI/BIOS启动文件，全新生成标准引导配置，重度引导丢失一键修复")

    def _decode(self, data):
        return self.boot_detector.decode(data)

    def _run(self, cmd, desc=""):
        return self.boot_detector.run(cmd, desc)

    def _run_get(self, cmd, desc=""):
        return self.boot_detector.run_get(cmd, desc)

    def _is_admin(self):
        return self.boot_detector.is_admin()

    def _auto_load_bcd(self):
        """自动加载BCD引导信息（只在第一次调用时执行）"""
        if self._bcd_auto_loaded:
            return
        self._bcd_auto_loaded = True

        if not self._is_admin():
            self._log("提示: 当前为普通用户模式，无法读取BCD信息。如需管理引导，请以管理员身份运行程序。")
            self._set_status("普通用户模式，无法读取BCD")
            return
        self._log("自动加载BCD引导信息...")
        self._refresh_bcd_list()

    def _bcd_set_default(self):
        idx = self.bcd_combo.current()
        if idx < 0:
            messagebox.showwarning("警告", "请选择要设为默认的启动项", parent=self.parent.master)
            return
        guid = self.bcd_entries[idx]["guid"]
        if not guid:
            messagebox.showwarning("警告", "无法获取标识符", parent=self.parent.master)
            return
        bcd_args = self._get_bcd_args()
        ok, _ = self._run_get(["bcdedit"] + bcd_args + ["/default", guid], f"设置默认:{guid}")
        if ok:
            self._set_status(f"已设为默认: {self.bcd_entries[idx].get('desc', guid)}")
            self._refresh_bcd_list()
        else:
            messagebox.showerror("失败", "设置默认失败", parent=self.parent.master)

    def _get_selected_guid(self):
        """获取当前选中的引导项GUID"""
        idx = self.bcd_combo.current()
        if idx < 0:
            return ""
        return self.bcd_entries[idx]["guid"]

    def _get_selected_name(self):
        """获取当前选中的引导项名称"""
        idx = self.bcd_combo.current()
        if idx < 0:
            return ""
        return self.bcd_entries[idx]["name"]

    def _on_bcd_combo_select(self, event=None):
        """下拉框选择变化时加载属性"""
        guid = self._get_selected_guid()
        if not guid:
            return
        self._load_entry_props(guid)

    def _load_entry_props(self, guid):
        """加载指定GUID的属性到右侧表格"""
        self.bcd_prop_tree.delete(*self.bcd_prop_tree.get_children())
        bcd_args = self._get_bcd_args()
        ok, out = self._run_get(["bcdedit"] + bcd_args + ["/enum", guid], f"枚举:{guid}")
        if not ok:
            return

        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue
            if _BOOT_SECTION_TITLES_RE.search(line):
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            key = parts[0].strip()
            val = parts[1].strip()
            if not (key and val):
                continue
            self.bcd_prop_tree.insert("", tk.END, values=(key, val))

    def _clear_prop_tree(self):
        """清空右侧属性表格"""
        self.bcd_prop_tree.delete(*self.bcd_prop_tree.get_children())

    def _on_prop_tree_resize(self, event):
        """属性表格尺寸变化时，按 35:65 比例自适应分配两列宽度"""
        tree_width = self.bcd_prop_tree.winfo_width()
        if tree_width < 2:
            return
        prop_w = int(tree_width * 0.35)
        val_w = tree_width - prop_w
        self.bcd_prop_tree.column("property", width=prop_w)
        self.bcd_prop_tree.column("value", width=val_w)

    # 常见 BCD 属性可接受值
    _COMMON_PROP_CHOICES = {
        "path": [
            "\\Windows\\System32\\boot\\winload.efi",
            "\\Windows\\System32\\boot\\winload.exe",
            "\\Windows\\System32\\winload.efi",
            "\\Windows\\System32\\winload.exe",
        ],
        "winpe": ["Yes", "No"],
        "detecthal": ["Yes", "No"],
        "locale": ["zh-CN", "en-US", "ja-JP", "ko-KR"],
        "inherit": ["{bootloadersettings}", "{globalsettings}", "{hypervisorsettings}"],
        "nx": ["OptIn", "OptOut", "AlwaysOn", "AlwaysOff"],
        "pae": ["ForceEnable", "ForceDisable", "Default", "Enable", "Disable"],
        "useplatformtick": ["Yes", "No"],
        "disabledynamictick": ["Yes", "No"],
        "hypervisorlaunchtype": ["Auto", "On", "Off"],
    }

    def _on_prop_edit(self, event):
        region = self.bcd_prop_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.bcd_prop_tree.identify_column(event.x)
        item = self.bcd_prop_tree.identify_row(event.y)
        if not item:
            return
        values = self.bcd_prop_tree.item(item, "values")
        if not values:
            return
        prop_name, prop_value = values[0], values[1]

        if col == "#2":
            self._edit_prop_value(item, prop_name, prop_value)
        else:
            copy_text = prop_name
            self.parent.master.clipboard_clear()
            self.parent.master.clipboard_append(copy_text)
            self._set_status(f"已复制: {copy_text}")

    def _edit_prop_value(self, item, prop_name, prop_value):
        """内联编辑属性值，修改立即生效"""
        guid = self._get_selected_guid()
        if not guid:
            return

        bbox = self.bcd_prop_tree.bbox(item, "#2")
        if not bbox:
            return
        x, y, width, height = bbox

        choices = self._COMMON_PROP_CHOICES.get(prop_name)
        if choices:
            # 有预设值：显示下拉选择
            combo = ttk.Combobox(self.bcd_prop_tree, values=choices, state="readonly", width=30)
            combo.set(prop_value)
            combo.place(x=x, y=y, width=width, height=height)
            combo.focus_set()

            def on_combo_select(_event, item=item, prop_name=prop_name, guid=guid):
                try:
                    new_value = combo.get().strip()
                    combo.destroy()
                except tk.TclError:
                    return
                if new_value and new_value != prop_value:
                    self._apply_prop_change(guid, item, prop_name, new_value)

            combo.bind("<<ComboboxSelected>>", on_combo_select)
            combo.bind("<FocusOut>", lambda e: combo.destroy())
            combo.bind("<Escape>", lambda e: combo.destroy())
        else:
            # 无预设值：自由输入
            entry = ttk.Entry(self.bcd_prop_tree, width=30)
            entry.insert(0, prop_value)
            entry.place(x=x, y=y, width=width, height=height)
            entry.focus_set()
            entry.select_range(0, tk.END)

            def on_focus_out(_event, item=item, prop_name=prop_name, guid=guid):
                new_value = entry.get().strip()
                entry.destroy()
                if new_value and new_value != prop_value:
                    self._apply_prop_change(guid, item, prop_name, new_value)

            entry.bind("<FocusOut>", on_focus_out)
            entry.bind("<Return>", lambda e: (on_focus_out(e), self.bcd_prop_tree.focus_set()))
            entry.bind("<Escape>", lambda e: entry.destroy())

    def _apply_prop_change(self, guid, item, prop_name, new_value):
        """立即应用属性修改到 BCD"""
        bcd_args = self._get_bcd_args()
        if self._run(
            ["bcdedit"] + bcd_args + ["/set", guid, prop_name, new_value],
            f"设置:{prop_name}={new_value}"
        ):
            self.bcd_prop_tree.set(item, "value", new_value)
            self._set_status(f"已修改: {prop_name} = {new_value}")
        else:
            messagebox.showerror("失败", f"设置 {prop_name} 失败", parent=self.parent.master)

    def _on_prop_right_click(self, event):
        """右键菜单：删除字段"""
        item = self.bcd_prop_tree.identify_row(event.y)
        if not item:
            return
        values = self.bcd_prop_tree.item(item, "values")
        if not values:
            return
        prop_name = values[0]

        menu = tk.Menu(self.bcd_prop_tree, tearoff=0)
        menu.add_command(label=f"删除字段 \"{prop_name}\"", command=lambda: self._delete_prop_field(item, prop_name))
        menu.post(event.x_root, event.y_root)

    def _delete_prop_field(self, item, prop_name):
        """删除指定字段"""
        guid = self._get_selected_guid()
        if not guid:
            return

        if not messagebox.askyesno("确认", f"确定要删除字段 \"{prop_name}\" 吗？", parent=self.parent.master):
            return

        bcd_args = self._get_bcd_args()
        if self._run(
            ["bcdedit"] + bcd_args + ["/deletevalue", guid, prop_name],
            f"删除:{prop_name}"
        ):
            self.bcd_prop_tree.delete(item)
            self._set_status(f"已删除: {prop_name}")
        else:
            messagebox.showerror("失败", f"删除 {prop_name} 失败", parent=self.parent.master)

    def _copy_bcd_id(self):
        """已废弃：复制标识符功能已移除"""
        pass

    # ------------------------------------------------------------------
    # Tooltip 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _set_tooltip(widget, text):
        """为控件设置鼠标悬浮提示"""
        tooltip = None
        def _show(_event=None):
            nonlocal tooltip
            if tooltip is not None:
                return
            x, y = widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height() + 2
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{x}+{y}")
            label = ttk.Label(tooltip, text=text, background="#FFFFE0",
                              relief=tk.SOLID, borderwidth=1, padding=px(3),
                              font=font_scaled("", 9))
            label.pack()
        def _hide(_event=None):
            nonlocal tooltip
            if tooltip is not None:
                tooltip.destroy()
                tooltip = None
        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)

    # ------------------------------------------------------------------
    # 分区选择弹窗（单行布局，一次性选择，全局共享）
    # ------------------------------------------------------------------
    def _show_partition_dialog(self):
        """弹出分区选择弹窗，返回 (boot_drive, sys_drive, is_uefi) 或 (None, None, None)"""
        # 检测当前引导模式
        boot_env = self._detect_boot_environment()
        boot_mode = boot_env.get('boot_mode', 'bios')
        is_uefi = (boot_mode == 'uefi')

        # 默认值：UEFI引导=Z，BIOS引导=C；系统分区始终=C
        if is_uefi:
            boot_default = "Z"
        else:
            boot_default = boot_env.get('target_drive', 'C:')[0].upper()
        sys_default = boot_env.get('target_drive', 'C:')[0].upper()

        # 创建弹窗，跟随主窗口居中
        dialog = tk.Toplevel(self.parent.master)
        dialog.title("选择分区")
        dialog.transient(self.parent.master)
        dialog.grab_set()
        if self.icon_path and os.path.exists(self.icon_path):
            try:
                dialog.iconbitmap(self.icon_path)
            except Exception:
                pass

        # 计算居中位置（相对于主窗口）
        dialog.update_idletasks()
        main_x = self.parent.master.winfo_rootx()
        main_y = self.parent.master.winfo_rooty()
        main_w = self.parent.master.winfo_width()
        dialog_w = px(320)
        dialog_h = px(130)
        x = main_x + (main_w - dialog_w) // 2
        y = main_y + 100
        dialog.geometry(f"{dialog_w}x{dialog_h}+{x}+{y}")

        letters = [c for c in string.ascii_uppercase]

        # 第一行：引导分区 + 系统分区
        row1 = ttk.Frame(dialog)
        row1.pack(fill=tk.X, padx=px(15), pady=(px(15), px(5)))
        ttk.Label(row1, text="引导分区:").pack(side=tk.LEFT)
        boot_var = tk.StringVar(value=boot_default)
        ttk.Combobox(row1, textvariable=boot_var, values=letters,
                     state="readonly", width=6).pack(side=tk.LEFT, padx=px(5))
        ttk.Label(row1, text="系统分区:").pack(side=tk.LEFT, padx=(px(10), 0))
        sys_var = tk.StringVar(value=sys_default)
        ttk.Combobox(row1, textvariable=sys_var, values=letters,
                     state="readonly", width=6).pack(side=tk.LEFT, padx=px(5))

        # 第二行：UEFI 复选框
        row2 = ttk.Frame(dialog)
        row2.pack(fill=tk.X, padx=px(15), pady=px(5))
        uefi_var = tk.BooleanVar(value=is_uefi)
        ttk.Checkbutton(row2, text="目标系统为 UEFI", variable=uefi_var).pack(anchor=tk.W)

        # 第三行：确认 + 取消
        row3 = ttk.Frame(dialog)
        row3.pack(fill=tk.X, padx=px(15), pady=(px(5), px(15)))
        ttk.Button(row3, text="确认", command=lambda: _confirm(), width=8).pack(side=tk.RIGHT, padx=px(3))
        ttk.Button(row3, text="取消", command=dialog.destroy, width=8).pack(side=tk.RIGHT, padx=px(3))

        result = [None, None, None]

        def _confirm():
            bd = boot_var.get().strip().upper()
            sd = sys_var.get().strip().upper()
            target_uefi = uefi_var.get()
            if not bd or not sd:
                messagebox.showwarning("警告", "请选择系统分区和引导分区盘符", parent=dialog)
                return
            sys_drive_path = f"{sd}:\\"
            if not os.path.exists(os.path.join(sys_drive_path, "Windows", "System32")):
                messagebox.showwarning("警告", f"系统分区 {sd}: 未找到Windows目录", parent=dialog)
                return
            result[0] = bd
            result[1] = sd
            result[2] = target_uefi
            dialog.destroy()

        dialog.wait_window()
        return result[0], result[1], result[2]

    def _ensure_partition_selected(self):
        """确保已选择分区（首次调用时弹窗，后续使用缓存）"""
        if self._boot_drive and self._sys_drive and self._is_uefi is not None:
            return True
        boot_drive, sys_drive, is_uefi = self._show_partition_dialog()
        if boot_drive and sys_drive and is_uefi is not None:
            self._boot_drive = boot_drive
            self._sys_drive = sys_drive
            self._is_uefi = is_uefi
            self._update_partition_status()
            return True
        return False

    def _update_partition_status(self):
        """更新状态栏显示当前选择的分区"""
        if self._boot_drive and self._sys_drive and self._is_uefi is not None:
            mode = "UEFI" if self._is_uefi else "BIOS"
            self._set_status(f"引导分区: {self._boot_drive}: | 系统分区: {self._sys_drive}: | 模式: {mode}")

    # ------------------------------------------------------------------
    # 【重置】备份并删除BCD配置（原刷新按钮）
    # ------------------------------------------------------------------
    def _reset_boot(self):
        """备份并清空BCD引导配置，不生成任何引导文件"""
        if not self._is_admin():
            messagebox.showwarning("警告", "请以管理员身份运行程序", parent=self.parent.master)
            return
        boot_drive, sys_drive, is_uefi = self._show_partition_dialog()
        if not boot_drive or not sys_drive or is_uefi is None:
            return

        if is_uefi:
            bcd_path = f"{boot_drive}:\\EFI\\Microsoft\\Boot\\bcd"
        else:
            bcd_path = f"{boot_drive}:\\Boot\\bcd"

        self._log("=== 开始重置引导 ===")
        self._set_progress(10, "正在备份BCD...")

        # 1. 去除只读/隐藏/系统属性
        self._run(["attrib", "-h", "-s", "-r", bcd_path], "去除BCD文件属性")

        # 2. 备份
        bak_path = bcd_path + ".bak"
        try:
            if os.path.exists(bcd_path):
                shutil.copy2(bcd_path, bak_path)
                self._log(f"已备份BCD: {bcd_path} -> {bak_path}")
        except Exception as e:
            self._log(f"备份BCD失败: {e}")

        # 3. 删除
        self._set_progress(50, "正在删除BCD...")
        self._run(["cmd", "/c", "del", "/f", bcd_path], "删除BCD文件")

        self._set_progress(100, "重置完成")
        self._log("=== 重置完成：BCD已备份并删除，请使用「修复引导」来重建引导 ===")
        messagebox.showinfo("完成", "BCD已备份并删除，请使用「修复引导」来重建引导。", parent=self.parent.master)
        self._clear_progress()

    # ------------------------------------------------------------------
    # 【修复引导】bcdboot 完整重装全套启动文件（原复制标识符按钮）
    # ------------------------------------------------------------------
    def _repair_boot_full(self):
        """使用 bcdboot 完整重装全套EFI/BIOS启动文件"""
        if not self._is_admin():
            messagebox.showwarning("警告", "请以管理员身份运行程序", parent=self.parent.master)
            return
        boot_drive, sys_drive, is_uefi = self._show_partition_dialog()
        if not boot_drive or not sys_drive or is_uefi is None:
            return

        self._log("=== 开始完整修复引导 ===")

        if is_uefi:
            self._set_progress(10, "正在执行 bcdboot (UEFI)...")
            self._run(
                ["bcdboot", f"{sys_drive}:\\Windows", "/s", f"{boot_drive}:", "/f", "UEFI", "/l", "zh-CN"],
                f"bcdboot {sys_drive}:\\Windows /s {boot_drive}: /f UEFI /l zh-CN"
            )
        else:
            self._set_progress(10, "正在执行 bcdboot (BIOS)...")
            self._run(
                ["bcdboot", f"{sys_drive}:\\Windows", "/s", f"{boot_drive}:", "/l", "zh-CN"],
                f"bcdboot {sys_drive}:\\Windows /s {boot_drive}: /l zh-CN"
            )

        self._set_progress(100, "修复完成")
        self._log("=== 完整修复引导完成 ===")
        messagebox.showinfo("完成", "全套引导文件修复完成！", parent=self.parent.master)
        self._clear_progress()
        self._refresh_bcd_list()

    def _find_boot_entry_by_name(self, menu_name, wim_path=None):
        """根据菜单名称或 WIM 路径查找现有的引导项。

        返回: (guid, conflict_type) 或 (None, None)
        """
        bcd_args = self._get_bcd_args()
        ok, out = self._run_get(
            ["bcdedit"] + bcd_args + ["/enum", "all"], "查找现有引导项"
        )
        if not ok:
            return None, None

        self._log(f"正在查找菜单名称: {menu_name}")
        if wim_path:
            self._log(f"WIM 路径匹配: {wim_path}")

        target_wim_norm = None
        if wim_path:
            target_wim_norm = os.path.normpath(wim_path).lower()

        current_guid = ""
        current_desc = ""
        current_device = ""
        current_osdevice = ""
        in_valid_section = False

        def _check_and_return(g, desc, device, osdevice, wim_norm, name):
            if not g:
                return None, None
            if desc == name:
                return g, "name"
            if wim_norm:
                if self._match_wim_path(device, wim_norm) or self._match_wim_path(osdevice, wim_norm):
                    return g, "path"
            return None, None

        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue

            is_section_title = False
            for title in _BOOT_SECTION_TITLES:
                if line.startswith(title):
                    is_section_title = True
                    break
            if not is_section_title:
                for title in _ALL_BOOT_SECTION_TITLES:
                    if line.startswith(title):
                        is_section_title = True
                        break

            if is_section_title:
                if in_valid_section and current_guid:
                    g, ct = _check_and_return(current_guid, current_desc, current_device,
                                              current_osdevice, target_wim_norm, menu_name)
                    if g:
                        type_desc = "名称相同" if ct == "name" else "路径相同"
                        self._log(f"找到匹配的引导项 [{type_desc}]: {current_desc} ({current_guid})")
                        return g, ct

                in_valid_section = _BOOT_LOADER_RE.search(line) is not None
                current_guid = ""
                current_desc = ""
                current_device = ""
                current_osdevice = ""
                continue

            if not in_valid_section:
                continue

            if line.startswith(_PROP_IDENTIFIER):
                current_guid = self._parse_property_value(line)
                if current_guid:
                    if not (current_guid.startswith("{") and current_guid.endswith("}")):
                        current_guid = ""
            elif line.startswith(_PROP_DESCRIPTION):
                current_desc = self._parse_property_value(line)
                if current_desc == menu_name and current_guid:
                    self._log(f"找到同名引导项: {menu_name} ({current_guid})")
                    return current_guid, "name"
            elif line.lower().startswith(("device", "设备")):
                current_device = self._parse_property_value(line)
                if (wim_path and current_guid and
                        self._match_wim_path(current_device, target_wim_norm)):
                    self._log(f"找到同路径 WIM 引导项: {current_desc} ({current_guid})")
                    return current_guid, "path"
            elif line.lower().startswith(("osdevice", "os设备", "os 设备")):
                current_osdevice = self._parse_property_value(line)
                if (wim_path and current_guid and
                        self._match_wim_path(current_osdevice, target_wim_norm)):
                    self._log(f"找到同路径 WIM 引导项: {current_desc} ({current_guid})")
                    return current_guid, "path"

        if in_valid_section and current_guid:
            g, ct = _check_and_return(current_guid, current_desc, current_device,
                                      current_osdevice, target_wim_norm, menu_name)
            if g:
                type_desc = "名称相同" if ct == "name" else "路径相同"
                self._log(f"找到匹配的引导项 [{type_desc}]: {current_desc} ({current_guid})")
                return g, ct

        self._log(f"未找到匹配的引导项: {menu_name}")
        return None, None

    def _match_wim_path(self, device_str, target_wim_norm):
        """判断 bcdedit 的 device/osdevice 属性值是否指向同一个 WIM 文件"""
        if not device_str or not target_wim_norm:
            return False

        device_lower = device_str.lower()
        if "ramdisk=" not in device_lower:
            return False

        try:
            after_eq = device_lower.split("=", 1)[1]
            before_comma = after_eq.split(",", 1)[0]

            if "]" not in before_comma:
                return False

            prefix = before_comma.split("]", 1)[0].strip() + "]"
            bcd_relpath = before_comma.split("]", 1)[1]
            bcd_relpath_norm = os.path.normpath(bcd_relpath)

            target_drive, target_relpath = os.path.splitdrive(target_wim_norm)
            target_relpath_norm = os.path.normpath(target_relpath)

            if bcd_relpath_norm != target_relpath_norm:
                return False

            bcd_drive_lower = ""
            if prefix == "[boot]":
                try:
                    env_info = self._detect_boot_environment()
                    boot_mode = env_info.get("boot_mode", "bios")
                    if boot_mode == "uefi":
                        esp_mount = self._ensure_efi_mounted(env_info)
                        if esp_mount:
                            drive, _ = os.path.splitdrive(esp_mount)
                            bcd_drive_lower = drive.rstrip("\\").lower()
                    else:
                        target_drive = env_info.get("target_drive", "")
                        if target_drive:
                            bcd_drive_lower = target_drive.rstrip("\\").lower()
                except Exception:
                    bcd_drive_lower = ""
            else:
                bcd_drive_lower = prefix.strip("[]").lower()

            target_drive_lower = target_drive.rstrip("\\").lower()

            if bcd_drive_lower and (bcd_drive_lower == target_drive_lower):
                return True

            if not bcd_drive_lower and prefix == "[boot]":
                return True

            return False

        except Exception:
            return False

    def _bcd_delete_dialog(self):
        guid = self._get_selected_guid()
        name = self._get_selected_name()
        if not guid:
            messagebox.showwarning("警告", "请选择要删除的引导项", parent=self.parent.master)
            return
        if messagebox.askyesno("确认", f"确定要删除引导项?\n{name}", parent=self.parent.master):
            bcd_args = self._get_bcd_args()
            if self._run(
                ["bcdedit"] + bcd_args + ["/delete", guid, "/cleanup"],
                f"删除:{guid}"
            ):
                self._set_status(f"已删除: {name}")
                # 删除后强制刷新：清除所有缓存，确保下次读取时
                # 重新检测环境并读取最新 BCD 内容
                self._boot_env_cache = None
                self.boot_detector.clear_caches()
                self._refresh_bcd_list()
            else:
                messagebox.showerror("失败", "删除失败", parent=self.parent.master)

    def _remove_bcd_entry(self, guid):
        """从引导项列表中移除指定GUID的项，不重新加载BCD"""
        for i, entry in enumerate(self.bcd_entries):
            if entry["guid"] == guid:
                del self.bcd_entries[i]
                break

        current_values = list(self.bcd_combo["values"])
        new_values = [v for v in current_values if guid not in v]
        self.bcd_combo["values"] = new_values

        self._clear_prop_tree()

        # 如果还有剩余项，自动选中第一项
        if new_values:
            self.bcd_combo.current(0)
            self._load_entry_props(self.bcd_entries[0]["guid"])
        else:
            self.bcd_combo.set("")
            self._set_status("引导项列表为空")

    def _add_bcd_entry(self, guid, name):
        """添加新的引导项到列表，不重新加载BCD"""
        self.bcd_entries.append({"guid": guid, "name": name})

        current_values = list(self.bcd_combo["values"])
        current_values.append(f"{name} | {guid}")
        self.bcd_combo["values"] = current_values

        self.bcd_combo.current(len(current_values) - 1)
        self._load_entry_props(guid)

    def _toggle_bcd_filter(self):
        """切换显示全部/只显示有效引导项"""
        self.show_all_bcd = not self.show_all_bcd
        self.filter_btn.config(text="有效" if self.show_all_bcd else "全部")
        self._refresh_bcd_list()

    def _invalidate_caches(self):
        """清除所有缓存，强制下次操作重新检测"""
        self.boot_detector.clear_caches()
        self._log("已清除环境缓存")

    def _set_refresh_ui_state(self, enabled):
        """批量设置刷新期间按钮的启用状态"""
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in self._refresh_buttons:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _apply_refresh_result(self, ok, out, show_error_dialog):
        """在主线程中应用刷新结果（解析bcdedit输出并更新UI）

        这个方法在主线程中被 self.root.after(0, ...) 调用。
        """
        try:
            if not ok:
                self._set_status("读取BCD失败")
                if show_error_dialog:
                    messagebox.showerror("失败", "无法读取BCD信息", parent=self.parent.master)
                return

            # ---- 第一步：按节解析 bcdedit 输出（含多行属性） ----
            lines = out.split("\n")
            sections = []
            i = 0
            n = len(lines)
            _BRACE_RE = re.compile(r'^\{[^}]+\}$')

            while i < n:
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue

                next_line = lines[i + 1].strip() if i + 1 < n else ""
                is_section_title = next_line and set(next_line) == {'-'}

                if is_section_title:
                    section = {
                        "section_type": line,
                        "identifier": "",
                        "description": "",
                        "props": {},
                        "prop_lists": {},
                    }
                    i += 1
                    if i < n and set(lines[i].strip()) == {'-'}:
                        i += 1

                    current_prop_name = None
                    while i < n:
                        prop_line = lines[i].strip()
                        if not prop_line:
                            i += 1
                            continue
                        if i + 1 < n:
                            nxt = lines[i + 1].strip()
                            if nxt and set(nxt) == {'-'}:
                                break
                        parts = prop_line.split(None, 1)
                        if len(parts) >= 2:
                            prop_name = parts[0].strip().lower()
                            prop_value = parts[1].strip()
                            if prop_name in ('identifier', '标识符'):
                                section["identifier"] = prop_value
                            elif prop_name in ('description', '描述'):
                                section["description"] = prop_value
                            brace_match = _BRACE_RE.match(prop_value)
                            if brace_match:
                                if prop_name not in section["prop_lists"]:
                                    section["prop_lists"][prop_name] = []
                                section["prop_lists"][prop_name].append(prop_value)
                                current_prop_name = prop_name
                            else:
                                section["props"][prop_name] = prop_value
                                current_prop_name = None
                            i += 1
                        else:
                            if current_prop_name:
                                brace_match = _BRACE_RE.match(prop_line)
                                if brace_match:
                                    section["prop_lists"].setdefault(current_prop_name, []).append(prop_line)
                            i += 1

                    sections.append(section)
                else:
                    i += 1

            # ---- 第二步：构建查找表 ----
            sections_by_id = {}
            sections_by_id_lower = {}
            for s in sections:
                if s["identifier"]:
                    sections_by_id[s["identifier"]] = s
                    sections_by_id_lower[s["identifier"].lower()] = s

            # ---- 第三步：确定显示列表 ----
            bootmgr = (
                sections_by_id.get("{bootmgr}")
                or sections_by_id_lower.get("{bootmgr}")
            )

            menu_item_ids = []
            if bootmgr:
                for key, vals in bootmgr["prop_lists"].items():
                    if key == 'displayorder' or key == '显示顺序':
                        menu_item_ids.extend(vals)
                if not menu_item_ids:
                    for key in bootmgr["props"]:
                        if 'default' in key:
                            dv = bootmgr["props"][key]
                            if _BRACE_RE.match(dv):
                                menu_item_ids.append(dv)

            alias_map = {}
            if bootmgr:
                for prop_key, val in bootmgr["props"].items():
                    if 'default' in prop_key and _BRACE_RE.match(val):
                        alias_map["{default}"] = val
                        alias_map["{default}".lower()] = val
                for prop_key, vals in bootmgr["prop_lists"].items():
                    if 'default' in prop_key and vals and _BRACE_RE.match(vals[0]):
                        alias_map["{default}"] = vals[0]
                        alias_map["{default}".lower()] = vals[0]

            if self.show_all_bcd:
                filtered_sections = []
                for s in sections:
                    if not s["identifier"]:
                        continue
                    if s["identifier"].lower() == "{current}":
                        continue
                    filtered_sections.append(s)
            else:
                filtered_sections = []
                seen_guids = set()
                for item_id in menu_item_ids:
                    item_id_lower = item_id.lower()
                    resolved_id = alias_map.get(item_id_lower, item_id)
                    sec = (
                        sections_by_id.get(resolved_id)
                        or sections_by_id_lower.get(resolved_id.lower())
                        or sections_by_id.get(item_id)
                        or sections_by_id_lower.get(item_id_lower)
                    )
                    if sec and sec["identifier"]:
                        guid_key = sec["identifier"].lower()
                        if guid_key not in seen_guids:
                            filtered_sections.append(sec)
                            seen_guids.add(guid_key)

                if not filtered_sections:
                    for s in sections:
                        if not s["identifier"]:
                            continue
                        if s["identifier"].lower() in ("{current}", "{bootmgr}", "{fwbootmgr}"):
                            continue
                        s_type = s["section_type"]
                        if "Boot Loader" in s_type or "启动加载器" in s_type:
                            filtered_sections.append(s)

            # ---- 第五步：填充下拉框（UI操作，必须在主线程） ----
            combo_values = []
            self.bcd_entries = []
            for sec in filtered_sections:
                desc = sec["description"] or sec["identifier"] or "(无描述)"
                combo_values.append(desc)
                self.bcd_entries.append({
                    "guid": sec["identifier"],
                    "name": desc,
                    "section_type": sec["section_type"],
                })

            self.bcd_combo["values"] = combo_values
            if combo_values:
                self.bcd_combo.current(0)
                self._load_entry_props(self.bcd_entries[0]["guid"])

            self._set_progress(100, f"已加载 {len(self.bcd_entries)} 个引导项")
            self._set_status(f"已加载 {len(self.bcd_entries)} 个引导项")
        finally:
            # 无论成功失败，都恢复按钮状态
            self._refresh_busy = False
            self._set_refresh_ui_state(True)

    def _refresh_bcd_list(self, show_error_dialog=True):
        """异步刷新引导项下拉列表（bcdedit在后台线程执行，不阻塞UI）

        BCD 结构：
        - {bootmgr} = Windows 启动管理器 = 父节（启动菜单配置，含 displayorder、default、timeout 等）
        - 各 Windows Boot Loader 节 = 子节（被 {bootmgr} 的 displayorder 引用，就是启动菜单中看到的"Windows 11"、"WindowsPE"等）

        两种显示模式：
        - 默认模式（show_all_bcd=False）：只显示 {bootmgr} 的 displayorder 中列出的子项
        - 高级模式（show_all_bcd=True）：显示 BCD 中所有节（包括 {bootmgr}、{fwbootmgr}、各种 settings 等）
        """
        # 防止重复刷新
        if self._refresh_busy:
            return
        self._refresh_busy = True
        self._set_refresh_ui_state(False)

        # 立即清空显示并显示加载状态
        self.bcd_combo.set("")
        self.bcd_entries = []
        self._clear_prop_tree()
        self._set_progress(20, "正在读取BCD...")
        self._set_status("正在读取BCD，请稍候...")

        # 在后台线程中执行 bcdedit（耗时操作，会阻塞UI）
        def _worker():
            try:
                bcd_args = self._get_bcd_args()
                ok, out = self._run_get(["bcdedit"] + bcd_args + ["/enum", "all"], "读取BCD")
            except Exception as e:
                ok, out = False, str(e)
            # 完成后回到主线程解析并更新UI
            self.root.after(0, lambda: self._apply_refresh_result(ok, out, show_error_dialog))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def add_boot_entry_from_test(self, wim_path, menu_name, add_to_display=True, progress_callback=None, timeout=5):
        """从启动测试模块调用添加引导（统一接口）

        Args:
            wim_path: WIM文件路径
            menu_name: 菜单名称
            add_to_display: 是否添加到显示列表
            progress_callback: 进度回调函数 (current, max, message)

        Returns:
            (success, guid): 成功状态和GUID
        """
        if progress_callback:
            progress_callback(60, 100, "正在创建引导项...")

        if not self._ensure_ramdisk_options():
            self._set_status("无法准备 boot.sdi，请以管理员身份运行")
            return False, None

        bcd_args = self._get_bcd_args()

        create_cmd = ["bcdedit"] + bcd_args + ["/create", "/d", menu_name, "/application", "osloader"]
        ok, out = self._run_get(create_cmd, "创建引导项")
        if not ok:
            self._set_status("创建引导项失败")
            return False, None

        guid = self._extract_guid(out)
        if not guid:
            self._set_status("获取GUID失败")
            return False, None

        if progress_callback:
            progress_callback(70, 100, "正在配置引导项...")

        wim_drive, wim_rel = self._split_drive_abs(wim_path)
        # 参考 WIT：WIM 位于引导分区时用 [boot]，启动时最可靠
        device_str = f"ramdisk=[boot]{wim_rel},{{ramdiskoptions}}"
        self._log(f"device: {device_str}")

        env_info = self._detect_boot_environment()
        boot_mode = env_info['boot_mode']
        # 参考 WIT 可正常启动的路径格式：\Windows\System32\boot\winload.*
        winload = (
            "\\Windows\\System32\\boot\\winload.efi"
            if boot_mode == 'uefi'
            else "\\Windows\\System32\\boot\\winload.exe"
        )
        self._log(f"使用引导加载器: {winload}")

        cmd_list = [
            (["bcdedit"] + bcd_args + ["/set", guid, "device", device_str], "device"),
            (["bcdedit"] + bcd_args + ["/set", guid, "osdevice", device_str], "osdevice"),
            (["bcdedit"] + bcd_args + ["/set", guid, "path", winload], "path"),
            (["bcdedit"] + bcd_args + ["/set", guid, "systemroot", "\\Windows"], "systemroot"),
            (["bcdedit"] + bcd_args + ["/set", guid, "winpe", "Yes"], "winpe"),
            (["bcdedit"] + bcd_args + ["/set", guid, "detecthal", "Yes"], "detecthal"),
            (["bcdedit"] + bcd_args + ["/deletevalue", guid, "nx"], "删除nx"),
        ]
        if add_to_display:
            cmd_list.append((["bcdedit"] + bcd_args + ["/displayorder", guid, "/addlast"], "displayorder"))
            cmd_list.append((["bcdedit"] + bcd_args + ["/timeout", str(timeout)], f"timeout={timeout}"))

        total_cmds = len(cmd_list)
        for i, (cmd, desc) in enumerate(cmd_list):
            if progress_callback:
                progress_callback(70 + int(25 * (i + 1) / total_cmds), 100, f"设置 {desc}...")
            if not self._run(cmd, f"设置{desc}"):
                self._set_status(f"配置引导项失败: {desc}")
                return False, None

        if progress_callback:
            progress_callback(95, 100, "引导项添加完成")
        self._set_status(f"引导项已添加: {guid}")
        return True, guid

    def find_boot_entry_by_wim_path(self, wim_path):
        """根据WIM文件路径查找现有引导项

        Args:
            wim_path: WIM文件路径

        Returns:
            guid: 找到的GUID，未找到返回None
        """
        bcd_args = self._get_bcd_args()
        ok, out = self._run_get(["bcdedit"] + bcd_args + ["/enum", "all"], "查找现有引导项")
        if not ok:
            return None

        wim_norm = os.path.normpath(wim_path).lower()
        wim_drive, wim_rel = self._split_drive_abs(wim_norm)
        self._log(f"匹配目标: [{wim_drive}]{wim_rel}")

        current_guid = None
        wim_filename = os.path.basename(wim_norm)

        # 匹配 ramdisk=[C:]\path\file.wim,{options}
        ramdisk_re = re.compile(r'ramdisk=\[([^\]]+)\]([^\s,]+)', re.IGNORECASE)

        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue

            line_lower = line.lower()

            guid_match = _GUID_RE.search(line)
            if guid_match and ("identifier" in line_lower or "标识符" in line):
                current_guid = guid_match.group(0)
                continue

            if "ramdisk" in line_lower and wim_filename in line_lower:
                wim_match = ramdisk_re.search(line)
                if not wim_match:
                    continue

                dev_prefix = wim_match.group(1).lower().strip()
                dev_path = wim_match.group(2).strip()
                dev_path_norm = "\\" + os.path.normpath(dev_path).lower().lstrip("\\")

                if dev_prefix == "locate":
                    if dev_path_norm == wim_rel or dev_path_norm.endswith(wim_rel):
                        if current_guid:
                            self._log(f"找到相同WIM路径的引导项: {wim_path} ({current_guid})")
                            return current_guid
                elif dev_prefix == "boot":
                    # [boot] 前缀 → 根据启动模式映射到对应盘符
                    #   UEFI: [boot] = ESP 分区 (Z:)
                    #   BIOS: [boot] = 活动分区 (C:)
                    try:
                        boot_drive = ""
                        env_info = self._detect_boot_environment()
                        boot_mode = env_info.get("boot_mode", "bios")
                        if boot_mode == "uefi":
                            esp_mount = self._ensure_efi_mounted(env_info)
                            if esp_mount:
                                d, _ = os.path.splitdrive(esp_mount)
                                boot_drive = d.lower()
                        else:
                            target_drive = env_info.get("target_drive", "")
                            if target_drive:
                                boot_drive = target_drive.rstrip("\\").lower()
                        if boot_drive and boot_drive == wim_drive and dev_path_norm == wim_rel:
                            if current_guid:
                                self._log(f"找到相同WIM路径的引导项: {wim_path} ({current_guid})")
                                return current_guid
                    except Exception:
                        pass
                else:
                    dev_prefix_fixed = dev_prefix.rstrip(":") + ":"
                    if dev_prefix_fixed == wim_drive and dev_path_norm == wim_rel:
                        if current_guid:
                            self._log(f"找到相同WIM路径的引导项: {wim_path} ({current_guid})")
                            return current_guid

        self._log(f"未找到WIM路径对应的引导项: {wim_path}")
        return None