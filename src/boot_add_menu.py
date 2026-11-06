# -*- coding: utf-8 -*-
"""添加引导菜单模块 - WIM/ISO启动项添加对话框"""

import os
import subprocess
import shutil
import ctypes
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dpi_utils import px


class BootAddMenu:
    """添加引导菜单对话框"""

    def __init__(self, boot_manager):
        self._boot_mgr = boot_manager
        # 快捷引用
        self._log = boot_manager._log
        self._set_status = boot_manager._set_status
        self._set_progress = boot_manager._set_progress
        self._is_admin = boot_manager._is_admin
        self._get_bcd_args = boot_manager._get_bcd_args
        self._run = boot_manager._run
        self._run_get = boot_manager._run_get
        self._decode = boot_manager._decode
        self._ensure_ramdisk_options = boot_manager._ensure_ramdisk_options
        self._find_boot_entry_by_name = boot_manager._find_boot_entry_by_name
        self._add_bcd_entry = boot_manager._add_bcd_entry
        self._detect_boot_environment = boot_manager._detect_boot_environment
        self._extract_guid = boot_manager._extract_guid
        self._split_drive_abs = boot_manager._split_drive_abs
        self.boot_detector = boot_manager.boot_detector

        self.wimlib_exe = boot_manager.wimlib_exe
        self.sevenz_exe = boot_manager.sevenz_exe
        self.icon_path = boot_manager.icon_path
        self.parent = boot_manager.parent

    # ------------------------------------------------------------------
    # 对话框工具方法
    # ------------------------------------------------------------------
    def _create_dialog(self, title, size="450x320"):
        dialog = tk.Toplevel(self.parent.master)
        dialog.title(title)
        parts = size.split("x")
        dialog.geometry(f"{px(int(parts[0]))}x{px(int(parts[1]))}")
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

    # ------------------------------------------------------------------
    # 核心：执行 bcdedit 命令并检查结果
    # ------------------------------------------------------------------
    def _run_bcdedit(self, args, desc=""):
        """执行 bcdedit 命令，成功返回 True"""
        cmd = ["bcdedit"] + self._get_bcd_args() + args
        ok = self._run(cmd, desc)
        if not ok:
            self._log(f"BCD命令失败: {desc}")
        return ok

    def _run_bcdedit_get(self, args, desc=""):
        """执行 bcdedit 命令并捕获输出"""
        cmd = ["bcdedit"] + self._get_bcd_args() + args
        return self._run_get(cmd, desc)

    # ------------------------------------------------------------------
    # 核心：构建 WIM 的 device/osdevice 字符串
    # ------------------------------------------------------------------
    def _get_boot_partition_drive(self):
        """获取当前系统引导分区的盘符（如 'Z:' 或 'C:'）"""
        boot_env = self._detect_boot_environment()
        boot_mode = boot_env.get('boot_mode', 'bios')
        if boot_mode == 'uefi':
            # UEFI: 引导分区是已挂载的 ESP 分区
            efi_mount = self.boot_detector.ensure_efi_mounted(boot_env)
            if efi_mount:
                return efi_mount.rstrip('\\').rstrip(':') + ':'
            return None
        else:
            # BIOS: 引导分区是活动分区（target_drive）
            target_drive = boot_env.get('target_drive')
            if target_drive:
                return target_drive.rstrip('\\').rstrip(':') + ':'
            return None
        return None

    def _build_wim_device_str(self, wim_path):
        """根据 WIM 路径构建 ramdisk 设备字符串。

        参考 WIT（可正常启动）采用的策略：
        - 如果 WIM 文件位于引导分区（UEFI=ESP，BIOS=活动分区），使用 [boot] 标识
          （启动时 bootmgr 不知道盘符，[boot] 是唯一可靠的方式）
        - 如果 WIM 位于其他分区，使用 [盘符:] 作为降级方案
        """
        wim_drive, wim_rel = self._split_drive_abs(wim_path)

        # 判断 WIM 是否位于引导分区
        boot_drive = self._get_boot_partition_drive()
        if boot_drive and (wim_drive == boot_drive):
            self._log(f"WIM 位于引导分区 ({boot_drive})，使用 [boot] 标识")
            return f"ramdisk=[boot]{wim_rel},{{ramdiskoptions}}"
        else:
            self._log(f"WIM 位于其他分区 ({wim_drive})，使用盘符标识")
            return f"ramdisk=[{wim_drive}]{wim_rel},{{ramdiskoptions}}"

    # ------------------------------------------------------------------
    # 核心：创建或更新引导项（统一逻辑，避免代码重复）
    # ------------------------------------------------------------------
    def _apply_wim_entry(self, guid, wim_path, is_new_entry=True, add_to_display=True, timeout=5):
        """
        应用 WIM 引导项的所有必需属性。

        Args:
            guid: 引导项 GUID
            wim_path: WIM 文件绝对路径
            is_new_entry: True=新建（需设置 path/systemroot/winpe 等），False=仅更新 device/osdevice
            add_to_display: True=添加到启动菜单显示列表，False=仅写入 BCD 不显示
            timeout: 启动菜单超时时间（秒）

        Returns:
            success: 是否成功
            error_msg: 失败时的错误信息
        """
        device_str = self._build_wim_device_str(wim_path)
        self._log(f"device 字符串: {device_str}")

        # 根据启动环境选择 winload
        # 参考 WIT 可正常启动的路径格式：\Windows\System32\boot\winload.efi
        # Windows PE 的 WIM 内 boot 加载器位于 \Windows\System32\boot\ 下
        env_info = self._detect_boot_environment()
        boot_mode = env_info.get('boot_mode', 'bios')
        winload = (
            "\\Windows\\System32\\boot\\winload.efi"
            if boot_mode == 'uefi'
            else "\\Windows\\System32\\boot\\winload.exe"
        )
        self._log(f"启动环境: {boot_mode.upper()}, 使用 winload: {winload}")

        # 必需的属性列表（命令参数, 描述）
        # ⚠️ 注意：device/osdevice 之外的属性（path/systemroot/winpe/detecthal）
        # 在"更新已有项"场景同样需要重新设置。例如：这个引导项之前可能是
        # 在 BIOS 机器创建的（path=winload.exe），现在在 UEFI 机器上更新，
        # 必须同步改为 winload.efi，否则会启动失败。bcdedit /set 是幂等的，
        # 重复执行不会出错。
        required_cmds = [
            (["/set", guid, "device", device_str], "设置 device"),
            (["/set", guid, "osdevice", device_str], "设置 osdevice"),
            (["/set", guid, "path", winload], "设置 path"),
            (["/set", guid, "systemroot", "\\Windows"], "设置 systemroot"),
            (["/set", guid, "winpe", "Yes"], "设置 winpe"),
            (["/set", guid, "detecthal", "Yes"], "设置 detecthal"),
        ]

        # 逐个执行，任何一个失败都立即返回
        for args, desc in required_cmds:
            if not self._run_bcdedit(args, desc):
                return False, f"{desc} 失败"

        # 确保项在启动菜单显示列表（displayorder）中：
        # - 新建项（is_new_entry=True 且 add_to_display=True）：添加到 displayorder 末尾
        # - 更新现有项（is_new_entry=False）：也需要确保在 displayorder 中，
        #   因为如果之前用了 /cleanup 删除，displayorder 中已被移除，此时
        #   bcdedit 中还能找到该项但它不会出现在启动菜单
        if add_to_display:
            if not self._run_bcdedit(
                ["/displayorder", guid, "/addlast"],
                "添加到启动菜单显示列表"
            ):
                self._log(
                    "警告: 无法添加到 displayorder，"
                    "这将导致启动菜单不显示该引导项"
                )
            if is_new_entry:
                self._run_bcdedit(["/timeout", str(timeout)], f"设置启动菜单超时{timeout}秒")

        return True, ""

    # ------------------------------------------------------------------
    # 核心：创建新的 WIM 引导项（底层统一入口）
    # ------------------------------------------------------------------
    def _create_wim_entry(self, name, wim_path, add_to_display=True, timeout=5):
        """
        创建新的 WIM 引导项。

        Args:
            add_to_display: 是否添加到启动菜单显示列表
            timeout: 启动菜单超时时间（秒）

        Returns:
            (success, guid_or_error)
        """
        # 1) 确保 {ramdiskoptions} 存在并配置 boot.sdi
        if not self._ensure_ramdisk_options():
            return False, "无法准备 boot.sdi，请以管理员身份运行"

        # 2) 创建引导项
        ok, out = self._run_bcdedit_get(
            ["/create", "/d", name, "/application", "osloader"],
            "创建引导项"
        )
        if not ok:
            return False, "创建引导项失败"

        guid = self._extract_guid(out)
        if not guid:
            return False, "创建引导项失败：未能解析 GUID"
        self._log(f"获得新引导项 GUID: {guid}")

        # 3) 应用所有必需属性；add_to_display=False 时不加入显示列表
        ok, err = self._apply_wim_entry(
            guid, wim_path, is_new_entry=True, add_to_display=add_to_display, timeout=timeout
        )
        if not ok:
            return False, err

        return True, guid

    # ------------------------------------------------------------------
    # 核心：更新现有 WIM 引导项（仅更新 device/osdevice 等与 WIM 相关的属性）
    # ------------------------------------------------------------------
    def _update_existing_entry(self, guid, name, wim_path):
        """更新现有引导项的 WIM 路径相关属性"""
        if not self._ensure_ramdisk_options():
            messagebox.showerror("失败", "无法准备 boot.sdi，请以管理员身份运行")
            return False
        ok, err = self._apply_wim_entry(guid, wim_path, is_new_entry=False)
        if not ok:
            messagebox.showerror("失败", f"更新引导项失败: {err}")
            return False
        self._log(f"已更新引导项: {name} ({guid})")
        self._set_status(f"已更新: {name}")
        return True

    # ------------------------------------------------------------------
    # 辅助：从 ISO 中提取 boot.wim
    # ------------------------------------------------------------------
    def _extract_boot_wim_from_iso(self, iso_path):
        """
        从 ISO 文件中提取 boot.wim 到临时目录。

        Returns:
            (success, wim_path, temp_dir)
        """
        temp_dir = tempfile.mkdtemp()
        boot_wim_dest = os.path.join(temp_dir, "boot.wim")

        sevenz_exe = self.sevenz_exe if (self.sevenz_exe and os.path.exists(self.sevenz_exe)) else "7z.exe"
        self._set_progress(10, "正在从ISO提取 boot.wim...")

        # 先尝试 sources/boot.wim，再尝试根目录的 boot.wim
        candidates = ["sources\\boot.wim", "boot.wim"]
        for rel in candidates:
            cmd = [sevenz_exe, "e", iso_path, rel, f"-o{temp_dir}", "-y"]
            self._log(f"执行: {' '.join(cmd)}")
            ok, _ = self._run_get(cmd, f"提取 {rel}")
            if ok and os.path.exists(boot_wim_dest):
                self._set_progress(30, "提取成功")
                self._log(f"boot.wim 已提取到: {boot_wim_dest}")
                return True, boot_wim_dest, temp_dir

        self._log("错误: 在 ISO 中未找到 boot.wim")
        return False, None, temp_dir

    # ------------------------------------------------------------------
    # 辅助：复制 WIM 到指定目录（委托给 boot_utils 共享逻辑）
    # ------------------------------------------------------------------
    def _copy_wim_to_target(self, wim_path, copy_dest):
        """复制 WIM 到目标目录，带空间和权限检查。

        Returns:
            (success, new_wim_path_or_error)
        """
        ok, result = self.boot_detector.copy_wim_to_dir(wim_path, copy_dest, log_fn=self._log)
        if not ok:
            hint = ""
            if "权限不足" in result and not self._is_admin():
                hint = "\n\n提示: 当前为普通用户，如果复制到C盘失败，请尝试D盘路径"
            return False, f"{result}{hint}"
        return True, result

    # ------------------------------------------------------------------
    # 辅助：从 WIM 文件中获取显示名称
    # ------------------------------------------------------------------
    def _get_wim_display_name(self, wim_path):
        """读取 WIM 的 Display Name 作为默认引导项名称"""
        ok, out = self._run_get([self.wimlib_exe, "info", wim_path], "读取WIM信息")
        if not ok:
            return None
        # 优先 Display Name，回退 Name
        display_name = None
        for line in out.split("\n"):
            line = line.strip()
            if line.startswith("Display Name:"):
                display_name = line.split(":", 1)[1].strip()
                break
            elif line.startswith("Name:") and display_name is None:
                display_name = line.split(":", 1)[1].strip()
        return display_name

    # ==================================================================
    # 对外：显示 WIM/ISO 添加对话框（主入口）
    # ==================================================================
    def show_add_wim_dialog(self, mode="ramdisk"):
        """显示添加 WIM/Windows 启动项对话框"""
        dialog = self._create_dialog(f"添加Windows启动项({mode})", "450x340")

        # --- 名称输入 ---
        ttk.Label(dialog, text="名称:").pack(anchor=tk.W, padx=px(10), pady=(px(10), 0))
        name_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=name_var, width=40).pack(fill=tk.X, padx=px(10), pady=px(5))

        # --- ISO/WIM 路径输入 ---
        ttk.Label(dialog, text="ISO/WIM文件路径:").pack(anchor=tk.W, padx=px(10), pady=(px(5), 0))
        source_var = tk.StringVar()
        source_frame = ttk.Frame(dialog)
        source_frame.pack(fill=tk.X, padx=px(10), pady=px(5))
        ttk.Entry(
            source_frame, textvariable=source_var, width=30
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # --- 复制到引导目录选项 ---
        copy_wim_var = tk.BooleanVar(value=False)
        copy_frame = ttk.Frame(dialog)
        copy_frame.pack(fill=tk.X, padx=px(10), pady=px(5))
        ttk.Checkbutton(
            copy_frame,
            text="复制WIM到引导目录(IsBoot目录)",
            variable=copy_wim_var
        ).pack(side=tk.LEFT, padx=(0, px(5)))

        default_copy_path = "C:\\IsBoot" if self._is_admin() else "D:\\IsBoot"
        copy_path_var = tk.StringVar(value=default_copy_path)
        copy_path_entry = ttk.Entry(
            copy_frame, textvariable=copy_path_var, width=20, state=tk.DISABLED
        )
        copy_path_entry.pack(side=tk.LEFT, padx=(0, px(5)))

        # --- 卷号输入（仅 WIM 模式下有意义）---
        ttk.Label(dialog, text="卷号:").pack(anchor=tk.W, padx=px(10), pady=(px(5), 0))
        idx_var = tk.StringVar(value="1")
        ttk.Entry(dialog, textvariable=idx_var, width=10).pack(anchor=tk.W, padx=px(10), pady=px(5))

        # --- 按钮行 ---
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=px(10), pady=px(10))

        # ------- 内部回调 -------
        def toggle_copy_path(*_args):
            copy_path_entry.config(
                state=tk.NORMAL if copy_wim_var.get() else tk.DISABLED
            )

        copy_wim_var.trace('w', toggle_copy_path)

        def browse_and_get_name():
            f = filedialog.askopenfilename(
                filetypes=[
                    ("ISO/WIM文件", "*.iso *.wim"),
                    ("ISO文件", "*.iso"),
                    ("WIM文件", "*.wim"),
                    ("所有文件", "*.*")
                ]
            )
            if not f:
                return
            source_var.set(f)
            lower = f.lower()

            # ISO 默认勾选复制
            if lower.endswith('.iso'):
                copy_wim_var.set(True)
                copy_path_entry.config(state=tk.NORMAL)
                # ISO 使用文件名作为默认名称
                name_var.set(os.path.splitext(os.path.basename(f))[0])
                return

            # WIM 尝试读取 Display Name
            if lower.endswith('.wim'):
                dn = self._get_wim_display_name(f)
                if dn:
                    name_var.set(dn)
                elif not name_var.get():
                    name_var.set(os.path.splitext(os.path.basename(f))[0])

        ttk.Button(
            source_frame, text="浏览", command=browse_and_get_name, width=6
        ).pack(side=tk.LEFT, padx=px(5))

        # ------- 主逻辑：点击"确定" -------
        def do_add():
            name = name_var.get().strip()
            source_path = os.path.abspath(source_var.get().strip()) if source_var.get() else ""
            if not name:
                messagebox.showwarning("警告", "请输入名称")
                return
            if not source_path or not os.path.exists(source_path):
                messagebox.showwarning("警告", "请选择存在的 ISO 或 WIM 文件")
                return

            lower = source_path.lower()
            if not (lower.endswith('.iso') or lower.endswith('.wim')):
                messagebox.showwarning("警告", "请选择 ISO 或 WIM 文件")
                return

            # ---- 阶段1：获取/提取 WIM 路径 ----
            wim_path = None
            temp_dir = None
            is_iso = lower.endswith('.iso')

            if is_iso:
                self._log(f"检测到 ISO 文件: {source_path}")
                ok, extracted_wim, temp_dir = self._extract_boot_wim_from_iso(source_path)
                if not ok:
                    messagebox.showerror("失败", "在ISO中未找到 boot.wim 文件")
                    _cleanup_temp(temp_dir)
                    return
                wim_path = extracted_wim
            else:
                wim_path = source_path

            wim_path = os.path.normpath(wim_path)

            # ---- 阶段2：可选复制 WIM 到引导目录 ----
            if copy_wim_var.get():
                copy_dest = copy_path_var.get().strip()
                if not copy_dest:
                    messagebox.showwarning("警告", "请输入复制目标路径")
                    _cleanup_temp(temp_dir)
                    return

                self._set_progress(40, "正在复制 WIM 到引导目录...")
                ok, result = self._copy_wim_to_target(wim_path, copy_dest)
                if not ok:
                    messagebox.showerror("复制失败", result)
                    _cleanup_temp(temp_dir)
                    return
                wim_path = result  # 更新为复制后的路径
                self._set_progress(50, "复制完成")

            # ---- 阶段3：处理同名/同路径引导项 ----
            existing_guid, conflict_type = self._find_boot_entry_by_name(name, wim_path)
            if existing_guid:
                if conflict_type == "path":
                    # 同文件：路径完全一致，提示原地更新
                    self._log(f"发现同路径引导项: {name} ({existing_guid})")
                    if messagebox.askyesno(
                        "确认",
                        f"已存在相同文件的引导项:\n{wim_path}\n\n"
                        f"是否更新其引导配置？\n"
                        f"(选择'否'将创建新的引导项)"
                    ):
                        self._update_existing_entry(existing_guid, name, wim_path)
                        _cleanup_temp(temp_dir)
                        dialog.destroy()
                        return
                else:
                    # 名称相同（但文件路径不同）：提示名称冲突
                    self._log(f"发现同名引导项: {name} ({existing_guid})")
                    if messagebox.askyesno(
                        "确认",
                        f"已存在同名引导项: {name}\n\n"
                        f"是否更新该引导项的 WIM 路径为:\n{wim_path}\n"
                        f"(选择'否'将创建新的引导项)"
                    ):
                        self._update_existing_entry(existing_guid, name, wim_path)
                        _cleanup_temp(temp_dir)
                        dialog.destroy()
                        return

            # ---- 阶段4：创建新引导项 ----
            ok, result = self._create_wim_entry(name, wim_path)
            if not ok:
                messagebox.showerror("失败", f"添加引导项失败: {result}")
                _cleanup_temp(temp_dir)
                return

            guid = result
            # 直接追加到下拉列表（不全部刷新）
            self._add_bcd_entry(guid, name)
            self._log(f"已添加引导项: {name} ({guid})")
            self._set_status(f"已添加: {name}")

            _cleanup_temp(temp_dir)
            dialog.destroy()

        def _cleanup_temp(tdir):
            """清理 ISO 提取产生的临时目录"""
            if tdir and os.path.isdir(tdir):
                try:
                    shutil.rmtree(tdir, ignore_errors=True)
                    self._log(f"已清理临时目录: {tdir}")
                except Exception:
                    pass

        ttk.Button(btn_frame, text="确定", command=do_add, width=10).pack(side=tk.LEFT, padx=px(5))
        ttk.Button(btn_frame, text="取消", command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=px(5))

    # ==================================================================
    # 对外：程序化添加 WIM 引导项（供外部调用，如 boot_test.py）
    # ==================================================================
    def add_wim_entry(self, wim_path, menu_name, add_to_menu=True, timeout=5):
        """
        添加 WIM 引导项。

        Args:
            wim_path: WIM 文件绝对路径（已复制到目标位置）
            menu_name: 菜单名称
            add_to_menu: 是否添加到启动菜单（False=临时测试模式，仅 BCD 注册）
            timeout: 启动菜单超时时间（秒）

        Returns:
            (success, guid_or_error)

        冲突处理:
            - 路径冲突（WIM 文件完全相同）: 静默更新已有项
            - 名称冲突（名称相同但文件不同）: 创建新项（不同文件应独立存在）
            - 无冲突: 创建新项
        """
        try:
            wim_path = os.path.normpath(wim_path)
            if not os.path.exists(wim_path):
                return False, f"WIM文件不存在: {wim_path}"

            # 检查冲突：严格路径匹配，不再做 basename 兜底
            existing_guid, conflict_type = self._find_boot_entry_by_name(menu_name, wim_path)
            if existing_guid:
                if conflict_type == "path":
                    # 路径冲突：同文件原地更新
                    self._log(f"发现同路径引导项，更新: {menu_name} ({existing_guid})")
                    self._update_existing_entry(existing_guid, menu_name, wim_path)
                    return True, existing_guid
                else:
                    # 名称冲突但路径不同：视为新文件，创建新项
                    self._log(
                        f"发现同名引导项 [{existing_guid}]（但路径不同），"
                        f"将创建新引导项: {menu_name}"
                    )
            else:
                self._log(f"未找到冲突，创建新引导项: {menu_name}")

            # 创建新项；add_to_menu=False 时不加入启动菜单显示列表
            ok, result = self._create_wim_entry(menu_name, wim_path, add_to_display=add_to_menu, timeout=timeout)
            if not ok:
                return False, result

            guid = result
            if add_to_menu:
                self._add_bcd_entry(guid, menu_name)
                self._set_status(f"已添加: {menu_name}")

            return True, guid

        except Exception as e:
            self._log(f"添加WIM引导项失败: {e}")
            return False, str(e)