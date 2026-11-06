# -*- coding: utf-8 -*-
"""启动测试模块 - 添加PE到启动菜单"""

import os
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import tempfile
from boot_utils import BootEnvironmentDetector
from dpi_utils import px, font_scaled
from file_searcher import search_file


class BootTest:
    def __init__(self, parent, root, base_dir, data_dir, sevenz_exe, wimlib_exe, dism_exe, log_callback, status_callback, progress_callback, switch_to_bcd_callback, boot_manager_callback=None, tab_frame=None, icon_path=None, boot_env_cache=None, boot_detector=None):
        self.root = root
        self.base_dir = base_dir
        self.data_dir = data_dir
        self.sevenz_exe = sevenz_exe
        self.wimlib_exe = wimlib_exe
        self.dism_exe = dism_exe
        self.icon_path = icon_path
        self._log = log_callback
        self._set_status = status_callback
        self._set_progress = progress_callback
        self._clear_progress = lambda: progress_callback(0, "")
        self._switch_to_bcd = switch_to_bcd_callback
        self._boot_mgr_callback = boot_manager_callback
        self._boot_mgr_instance = None
        self._boot_env_cache = boot_env_cache

        self.boot_mode = tk.StringVar(value="add")
        self.wait_time = tk.StringVar(value="5")
        self.menu_lang = tk.StringVar(value="zh-CN")
        self.legacy_menu = tk.BooleanVar(value=False)
        self.menu_name = tk.StringVar(value="Windows 10 PE")
        self.copy_pe = tk.BooleanVar(value=False)
        self.pe_drive = tk.StringVar(value="Z:")
        self.pe_path = tk.StringVar(value="\\IsBoot")
        self.file_source = tk.StringVar()
        self.restart_after = tk.BooleanVar(value=False)

        # 使用传入的boot_detector实例，或创建新的（兼容旧代码）
        self.boot_detector = boot_detector if boot_detector else BootEnvironmentDetector(log_callback)

        if tab_frame is not None:
            self.parent = tab_frame
        else:
            self.parent = ttk.Frame(parent)
            parent.add(self.parent, text="启动测试")

        # 先构建UI，再异步执行环境检测
        self._build_ui()
        self._bind_tab_events()
        
        # 标记是否已执行过环境检测（避免重复检测）
        self._env_detected = False
        
        # 异步执行环境检测和ESP挂载，避免阻塞UI
        self.root.after(100, self._async_detect_boot_environment)

    def _bind_tab_events(self):
        """绑定Tab切换事件，离开启动测试Tab时自动卸载ESP分区"""
        try:
            parent_notebook = self.parent.master
            if hasattr(parent_notebook, 'bind'):
                # 使用 "+" 前缀追加绑定，不覆盖原有事件处理
                parent_notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")
        except:
            pass

    def _on_tab_changed(self, event):
        """Tab切换事件处理"""
        try:
            parent_notebook = event.widget
            current_tab_index = parent_notebook.index("current")
            current_tab_text = parent_notebook.tab(current_tab_index, "text")

            # 如果切换到引导管理Tab，且只刷新一次环境信息
            if current_tab_text == "引导管理" and not self._env_detected:
                self._env_detected = True
                self._refresh_boot_environment()
        except:
            pass

    def _refresh_boot_environment(self):
        """刷新引导环境信息（供引导管理Tab调用）"""
        env_info = self.boot_detector.refresh_boot_environment()

    def _set_default_pe_path(self):
        """设置默认PE路径：检测ESP分区挂载状态，UEFI模式自动挂载ESP"""
        # 快速检测已挂载的ESP（Z:/Y:等常用盘符）
        existing_esp = None
        for letter in ("Z", "Y", "X"):
            path = f"{letter}:\\"
            if os.path.exists(path) and os.path.exists(os.path.join(path, "EFI")):
                existing_esp = letter
                break

        if existing_esp:
            self.pe_drive.set(f"{existing_esp}:")
            self._log(f"检测到{existing_esp}盘已挂载ESP，已自动选择{existing_esp}:", update_status=False)
        else:
            # 检测引导环境，如果是UEFI模式则尝试挂载ESP
            try:
                env_info = self.boot_detector.detect_boot_environment()
                boot_mode = env_info.get('boot_mode', 'bios')
                has_efi = env_info.get('has_efi', False)

                if boot_mode == 'uefi' and has_efi:
                    self._log("检测到UEFI模式，尝试挂载ESP分区...", update_status=False)
                    efi_mount = self.boot_detector.ensure_efi_mounted(env_info)
                    if efi_mount:
                        letter = efi_mount[0].upper()
                        self.pe_drive.set(f"{letter}:")
                        self._log(f"ESP分区已挂载到{letter}:盘，已自动选择ESP引导分区", update_status=False)
                    else:
                        self.pe_drive.set("C:")
                        self._log("ESP分区挂载失败，已选择C盘作为引导分区", update_status=False)
                else:
                    self.pe_drive.set("C:")
                    self._log("BIOS模式，已自动选择C盘作为引导分区", update_status=False)
            except Exception as e:
                self._log(f"检测引导环境失败: {e}，默认使用C盘")
                self.pe_drive.set("C:")

    def _async_detect_boot_environment(self):
        """异步执行环境检测和ESP挂载，避免阻塞UI"""
        try:
            # 如果 Z 盘已挂载 ESP，无需再次检测
            if os.path.exists("Z:\\EFI"):
                if self.pe_drive.get() != "Z:":
                    self.pe_drive.set("Z:")
                    self._log("检测到Z盘ESP已挂载，已自动选择Z:", update_status=False)
                return

            # 如果有缓存的环境检测结果，直接使用
            if self._boot_env_cache is not None:
                self._log("使用已缓存的引导环境检测结果", update_status=False)
                env_info = self._boot_env_cache
            else:
                # 检测引导环境
                self._log("正在检测引导环境...", update_status=False)
                env_info = self.boot_detector.detect_boot_environment()

            boot_mode = env_info.get('boot_mode', 'bios')
            has_efi = env_info.get('has_efi', False)

            if boot_mode == 'uefi' and has_efi:
                self._log("检测到UEFI模式，尝试挂载ESP分区到Z:盘...", update_status=False)
                efi_mount = self.boot_detector.ensure_efi_mounted(env_info)
                if efi_mount:
                    self.pe_drive.set("Z:")
                    self._log("ESP分区已挂载到Z:盘，已自动更新PE路径", update_status=False)
                else:
                    self._log("ESP分区挂载失败，保持使用C盘", update_status=False)
            else:
                self._log("BIOS模式，使用C盘作为引导分区", update_status=False)
                self.pe_drive.set("C:")
        except Exception as e:
            self._log(f"异步环境检测失败: {e}")

    def _build_ui(self):
        main_frame = ttk.Frame(self.parent, padding=px(3))
        main_frame.pack(fill=tk.BOTH, expand=True)

        main_content = ttk.LabelFrame(main_frame, text="添加PE到启动菜单", padding=px(5))
        main_content.pack(fill=tk.BOTH, expand=True)

        row1 = ttk.Frame(main_content)
        row1.pack(fill=tk.X, pady=px(2))
        ttk.Radiobutton(row1, text="添加到启动菜单", variable=self.boot_mode, value="add").pack(side=tk.LEFT, padx=px(5))
        ttk.Radiobutton(row1, text="临时测试一次（不加入菜单）", variable=self.boot_mode, value="test").pack(side=tk.LEFT, padx=px(5))
        ttk.Label(row1, text="等待时间").pack(side=tk.LEFT, padx=(px(10), px(2)))
        wait_combo = ttk.Combobox(row1, textvariable=self.wait_time, width=5, state="readonly")
        wait_combo['values'] = ['3', '5', '10', '15', '30']
        wait_combo.pack(side=tk.LEFT)

        row2 = ttk.Frame(main_content)
        row2.pack(fill=tk.X, pady=px(5))
        ttk.Label(row2, text="菜单语言").pack(side=tk.LEFT, padx=(0, px(5)))
        lang_combo = ttk.Combobox(row2, textvariable=self.menu_lang, width=8, state="readonly")
        lang_combo['values'] = ['zh-CN', 'en-US', 'zh-TW', 'ja-JP']
        lang_combo.pack(side=tk.LEFT, padx=(0, px(10)))
        ttk.Checkbutton(row2, text="传统菜单", variable=self.legacy_menu).pack(side=tk.LEFT)

        row3 = ttk.Frame(main_content)
        row3.pack(fill=tk.X, pady=px(5))
        ttk.Label(row3, text="菜单名称").pack(side=tk.LEFT, padx=(0, px(5)))
        name_combo = ttk.Combobox(row3, textvariable=self.menu_name, width=35)
        name_combo['values'] = [
            "Windows 10 PE",
            "Windows 11 PE",
            "Windows PE",
            "微PE工具箱",
            "系统维护",
        ]
        name_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, px(5)))
        ttk.Button(row3, text="查看引导", command=self._switch_to_bcd, width=8).pack(side=tk.LEFT)

        row4 = ttk.Frame(main_content)
        row4.pack(fill=tk.X, pady=px(5))
        ttk.Checkbutton(row4, text="复制PE包到", variable=self.copy_pe, command=self._toggle_copy_pe).pack(side=tk.LEFT, padx=(0, px(5)))
        
        drive_combo = ttk.Combobox(row4, textvariable=self.pe_drive, width=4, state="disabled")
        drive_combo['values'] = ['C:', 'D:', 'E:', 'F:', 'G:', 'H:', 'I:', 'J:', 'K:', 'L:', 'M:', 'N:', 'O:', 'P:', 'Q:', 'R:', 'S:', 'T:', 'U:', 'V:', 'W:', 'X:', 'Y:', 'Z:']
        drive_combo.pack(side=tk.LEFT, padx=(0, px(2)))
        
        path_entry = ttk.Entry(row4, textvariable=self.pe_path, width=12, state=tk.DISABLED)
        path_entry.pack(side=tk.LEFT, padx=(0, px(5)))
        ttk.Button(row4, text="打开", command=self._open_pe_path, width=5, state=tk.DISABLED).pack(side=tk.LEFT)
        ttk.Button(row4, text="列表", command=self._toggle_isboot_list, width=5, state=tk.DISABLED).pack(side=tk.LEFT, padx=(px(2), 0))
        self.open_btn = row4.winfo_children()[-2]
        self.list_btn = row4.winfo_children()[-1]

        row5 = ttk.Frame(main_content)
        row5.pack(fill=tk.X, pady=px(5))
        ttk.Label(row5, text="文件来源").pack(side=tk.LEFT, padx=(0, px(5)))
        source_entry = ttk.Entry(row5, textvariable=self.file_source, width=45)
        source_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, px(5)))
        ttk.Button(row5, text="搜索", command=self._search_source, width=5).pack(side=tk.LEFT, padx=(0, px(2)))
        ttk.Button(row5, text="浏览", command=self._browse_source, width=5).pack(side=tk.LEFT)

        # 「列表」展开面板（默认隐藏，点击列表按钮显示/隐藏）
        # 用于在当前页面直接展示 IsBoot 目录下的 wim/iso/sdi 文件，右键可直接删除，无需弹窗
        self.list_panel = ttk.Frame(main_content)
        # 不 pack，首次点击「列表」按钮后再决定显示或隐藏
        self.list_panel_info = ttk.Label(self.list_panel)
        self.list_panel_info.pack_forget()  # 记录是否已显示

        list_header = ttk.Frame(self.list_panel)
        ttk.Label(list_header, text="IsBoot 目录文件（右键可删除）", font=font_scaled("Microsoft YaHei", 9, "bold")).pack(side=tk.LEFT)
        ttk.Button(list_header, text="刷新", command=self._refresh_local_list, width=6).pack(side=tk.RIGHT, padx=(px(3), 0))
        ttk.Button(list_header, text="隐藏", command=self._hide_isboot_list, width=6).pack(side=tk.RIGHT)
        list_header.pack(fill=tk.X)

        list_tree_frame = ttk.Frame(self.list_panel)
        list_cols = ("name", "size", "mtime")
        self.list_tree = ttk.Treeview(list_tree_frame, columns=list_cols, show="headings", selectmode="extended", height=8)
        self.list_tree.heading("name", text="文件名")
        self.list_tree.heading("size", text="大小(MB)")
        self.list_tree.heading("mtime", text="修改时间")
        self.list_tree.column("name", width=260, anchor=tk.W)
        self.list_tree.column("size", width=100, anchor=tk.E)
        self.list_tree.column("mtime", width=140, anchor=tk.CENTER)
        self.list_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_vsb = ttk.Scrollbar(list_tree_frame, orient="vertical", command=self.list_tree.yview)
        list_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_tree.configure(yscrollcommand=list_vsb.set)
        list_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(px(3), 0))

        self.list_panel_status = ttk.Label(self.list_panel, text="", anchor=tk.W)
        self.list_panel_status.pack(fill=tk.X)

        # 右键菜单
        self._build_list_context_menu()

        btn_frame = ttk.Frame(main_content)
        btn_frame.pack(fill=tk.X, pady=(px(10), px(5)))
        ttk.Checkbutton(btn_frame, text="完成后：重启看看效果", variable=self.restart_after).pack(side=tk.LEFT, padx=px(5))
        ttk.Button(btn_frame, text="提交", command=self._execute, width=12).pack(side=tk.RIGHT, padx=px(5))

    def _toggle_copy_pe(self):
        state = tk.NORMAL if self.copy_pe.get() else tk.DISABLED
        for widget in self.parent.winfo_children():
            for frame in widget.winfo_children():
                for row in frame.winfo_children():
                    for child in row.winfo_children():
                        if isinstance(child, ttk.Combobox) and child.cget('textvariable') == str(self.pe_drive):
                            child.config(state=state)
                        if isinstance(child, ttk.Entry) and child.cget('textvariable') == str(self.pe_path):
                            child.config(state=state)
        self.open_btn.config(state=state)
        self.list_btn.config(state=state)

    def _open_pe_path(self):
        drive = self.pe_drive.get()
        path = self.pe_path.get()
        if not drive:
            messagebox.showwarning("提示", "请先选择目标盘符", parent=self.parent.master)
            return

        # 如果选择的是 Z: 或其他 ESP 分区盘符，直接尝试打开
        # Win10/11 系统层面隔离了 mountvol 挂载的 ESP 盘符，explorer 可能报"位置不可用"
        # 推荐用户用内置 IsBoot 列表直接删镜像
        drive_upper = (drive or "").upper().rstrip("\\") + ":"
        if drive_upper.startswith("Z:") or "Z:" in drive_upper:
            ok, msg = self.boot_detector.open_esp_folder(sub_path=path.lstrip("\\"))
            if ok:
                self._set_status(msg)
            else:
                messagebox.showwarning("打开失败", msg, parent=self.parent.master)
            return

        # 普通盘符（C:/D:/E: 等）直接打开
        full_path = drive.rstrip("\\") + "\\" + path.lstrip("\\")
        if not os.path.exists(full_path):
            try:
                os.makedirs(full_path, exist_ok=True)
            except OSError:
                messagebox.showwarning("警告", f"路径不存在: {full_path}", parent=self.parent.master)
                return
        try:
            os.startfile(full_path)
            self._set_status(f"已打开: {full_path}")
        except Exception as e:
            messagebox.showerror("打开失败", str(e), parent=self.parent.master)

    def _build_list_context_menu(self):
        """构建列表右键菜单"""
        self.list_menu = tk.Menu(self.root, tearoff=0)
        self.list_menu.add_command(label="删除选中文件", command=lambda: self._delete_selected_local())
        self.list_menu.add_command(label="全选", command=lambda: self._select_all_local(True))
        self.list_menu.add_command(label="取消全选", command=lambda: self._select_all_local(False))
        self.list_menu.add_separator()
        self.list_menu.add_command(label="刷新", command=self._refresh_local_list)
        self.list_menu.add_command(label="隐藏列表", command=self._hide_isboot_list)

    def _toggle_isboot_list(self):
        if not self.copy_pe.get():
            messagebox.showinfo("提示", "请先勾选「复制 PE 包」以指定目录", parent=self.parent.master)
            return

        if str(self.list_panel.winfo_manager()) != "":
            self._hide_isboot_list()
            return

        self.list_panel.pack(fill=tk.BOTH, expand=True, pady=(px(3), 0))
        self._refresh_local_list()

        self.list_tree.bind("<Button-3>", self._list_on_right_click)
        self.list_tree.bind("<Button-2>", self._list_on_right_click)

        try:
            self.list_btn.config(text="隐藏")
        except Exception:
            pass

    def _hide_isboot_list(self):
        """隐藏 IsBoot 列表面板"""
        try:
            self.list_panel.pack_forget()
        except Exception:
            pass
        try:
            self.list_btn.config(text="列表")
        except Exception:
            pass

    def _list_on_right_click(self, event):
        """在列表上右键弹出菜单"""
        try:
            self.list_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.list_menu.grab_release()

    def _refresh_local_list(self):
        """刷新本页面内嵌列表的数据"""
        drive = self.pe_drive.get() or ""

        # 清空现有条目
        for item in self.list_tree.get_children():
            self.list_tree.delete(item)

        files = self.boot_detector.list_isboot_files(
            target_drive=drive, extensions=['.wim', '.iso', '.sdi']
        )

        total_size = 0
        for f in files:
            size_mb = f.get("size_mb", 0)
            total_size += f.get("size", 0)
            mtime_str = ""
            mtime = f.get("mtime")
            if mtime:
                try:
                    mtime_str = mtime.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    mtime_str = ""
            self.list_tree.insert(
                "", tk.END,
                values=(f.get("name", ""), f"{size_mb:.2f}", mtime_str),
                tags=(f.get("path", ""),)  # 把完整路径保存在 item tags 里，删除时用
            )

        count = len(files)
        total_mb = total_size / (1024 * 1024) if total_size > 0 else 0
        self.list_panel_status.config(text=f"共 {count} 个文件，总计 {total_mb:.2f} MB")

    def _select_all_local(self, select):
        """全选/取消全选"""
        if select:
            for item in self.list_tree.get_children():
                self.list_tree.selection_add(item)
        else:
            self.list_tree.selection_remove(self.list_tree.selection())

    def _delete_selected_local(self):
        """右键/按钮：删除本页面列表中被选中的文件"""
        selected = self.list_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要删除的文件", parent=self.parent.master)
            return

        # 收集文件信息（从 tree 取 name，从 tags 取完整路径）
        targets = []  # [(path, name)]
        for item in selected:
            vals = self.list_tree.item(item, "values")
            tags = self.list_tree.item(item, "tags")
            path = ""
            if tags:
                path = tags[0]
            # 兜底：拼接完整路径
            if not path:
                drive = self.pe_drive.get() or ""
                path = os.path.join(drive.rstrip("\\") + "\\", "IsBoot", vals[0])
            targets.append((path, vals[0] if vals else ""))

        names_str = "\n".join(name for _, name in targets)
        if not messagebox.askyesno("确认删除", f"确定要删除以下 {len(targets)} 个文件？\n\n{names_str}\n\n此操作不可恢复！", parent=self.parent.master):
            return

        success = 0
        fail_msgs = []
        for path, name in targets:
            ok, msg = self.boot_detector.delete_isboot_file(path)
            if ok:
                success += 1
            else:
                fail_msgs.append(f"{name}: {msg}")

        # 刷新列表
        self._refresh_local_list()

        if success == len(targets):
            messagebox.showinfo("完成", f"已删除 {success} 个文件", parent=self.parent.master)
            self._set_status(f"已从 IsBoot 目录删除 {success} 个文件")
        else:
            msg = f"成功删除 {success}/{len(targets)} 个文件"
            if fail_msgs:
                msg += "\n\n失败详情:\n" + "\n".join(fail_msgs)
            messagebox.showwarning("部分失败", msg, parent=self.parent.master)

    def _search_source(self):
        """搜索ISO或WIM文件"""
        filepath = search_file(
            self.parent.master,
            icon_path=self.icon_path,
            title="搜索ISO或WIM文件",
            file_types={'.wim': 'WIM文件', '.iso': 'ISO文件'},
            default_drives=['D:\\'],
            default_depth=3
        )
        
        if filepath:
            self.file_source.set(filepath)
            self._auto_set_menu_name(filepath)
            if filepath.lower().endswith('.iso'):
                self.copy_pe.set(True)
                self._set_default_pe_path()
                self._toggle_copy_pe()

    def _browse_source(self):
        f = filedialog.askopenfilename(
            title="选择ISO或WIM文件",
            filetypes=[("ISO/WIM文件", "*.iso *.wim"), ("ISO文件", "*.iso"), ("WIM文件", "*.wim"), ("所有", "*.*")]
        )
        if f:
            self.file_source.set(f)
            self._auto_set_menu_name(f)
            if f.lower().endswith('.iso'):
                self.copy_pe.set(True)
                self._set_default_pe_path()
                self._toggle_copy_pe()

    def _auto_set_menu_name(self, filepath):
        if filepath.lower().endswith('.wim'):
            name = self._get_wim_display_name(filepath)
            if name:
                self.menu_name.set(name)
            self._check_wim_boot_menu(filepath)
        elif filepath.lower().endswith('.iso'):
            # ISO文件：提取后会是boot.wim，检测boot.wim是否已有引导菜单
            name = os.path.splitext(os.path.basename(filepath))[0]
            self.menu_name.set(name)
            self._check_iso_boot_menu(filepath)

    def _check_iso_boot_menu(self, iso_path):
        """检测ISO文件提取后的boot.wim是否已有对应的引导菜单（仅日志提示）"""
        if not iso_path or not os.path.exists(iso_path):
            return

        boot_add_menu = self._get_boot_add_menu()
        if not boot_add_menu:
            return

        wim_basename = "boot.wim"

        bcd_args = self._get_bcd_args()
        ok, out = self._run_get(["bcdedit"] + bcd_args + ["/enum", "all"], "检测ISO引导菜单")
        if not ok:
            return

        current_guid = ""
        current_desc = ""
        found_entries = {}

        for line in out.split("\n"):
            line_stripped = line.strip()
            line_lower = line_stripped.lower()

            if line_lower.startswith("identifier") or line_lower.startswith("标识符"):
                parts = line_stripped.split(None, 1)
                current_guid = parts[1].strip() if len(parts) > 1 else ""
            elif line_lower.startswith("description") or line_lower.startswith("描述"):
                parts = line_stripped.split(None, 1)
                current_desc = parts[1].strip() if len(parts) > 1 else ""
            elif "ramdisk=" in line_lower:
                if wim_basename in line_lower and current_guid:
                    if current_guid not in found_entries:
                        found_entries[current_guid] = current_desc

        if found_entries:
            self._log(f"检测到boot.wim已有 {len(found_entries)} 个引导菜单，将添加新项", update_status=False)
        else:
            self._log("boot.wim未检测到现有引导菜单，将添加新项", update_status=False)

    def _check_wim_boot_menu(self, wim_path):
        """检测WIM文件是否已有对应的引导菜单（仅日志提示）"""
        if not wim_path or not os.path.exists(wim_path):
            return

        boot_add_menu = self._get_boot_add_menu()
        if not boot_add_menu:
            return

        wim_basename = os.path.basename(os.path.normpath(wim_path).lower())

        bcd_args = self._get_bcd_args()
        ok, out = self._run_get(["bcdedit"] + bcd_args + ["/enum", "all"], "检测WIM引导菜单")
        if not ok:
            return

        current_guid = ""
        current_desc = ""
        found_entries = {}

        for line in out.split("\n"):
            line_stripped = line.strip()
            line_lower = line_stripped.lower()

            if line_lower.startswith("identifier") or line_lower.startswith("标识符"):
                parts = line_stripped.split(None, 1)
                current_guid = parts[1].strip() if len(parts) > 1 else ""
            elif line_lower.startswith("description") or line_lower.startswith("描述"):
                parts = line_stripped.split(None, 1)
                current_desc = parts[1].strip() if len(parts) > 1 else ""
            elif "ramdisk=" in line_lower:
                if wim_basename in line_lower and current_guid:
                    if current_guid not in found_entries:
                        found_entries[current_guid] = current_desc

        if found_entries:
            self._log(f"检测到{wim_basename}已有 {len(found_entries)} 个引导菜单，将添加新项", update_status=False)
        else:
            self._log(f"{wim_basename}未检测到现有引导菜单，将添加新项", update_status=False)

    def _get_wim_display_name(self, wim_path):
        try:
            if not self.wimlib_exe or not os.path.exists(self.wimlib_exe):
                return None
            cmd = [self.wimlib_exe, "info", wim_path]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            raw, _ = p.communicate()
            out = self._decode(raw)
            for line in out.split("\n"):
                line = line.strip()
                if line.startswith("[DISPLAY_NAME]"):
                    return line.split("=", 1)[1].strip()
                elif line.startswith("[DISPLAY_DESCRIPTION]"):
                    return line.split("=", 1)[1].strip()
            return os.path.splitext(os.path.basename(wim_path))[0]
        except:
            return os.path.splitext(os.path.basename(wim_path))[0]

    def _decode(self, data):
        return self.boot_detector.decode(data)

    def _run(self, cmd, desc=""):
        return self.boot_detector.run(cmd, desc)

    def _run_get(self, cmd, desc=""):
        return self.boot_detector.run_get(cmd, desc)

    def _show_toast(self, title, message, duration_ms=2500):
        """醒目横幅通知：显示在屏幕右下角，持续 duration_ms 毫秒后自动消失，无需用户点击。"""
        try:
            toast = tk.Toplevel(self.root)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            # 半透明背景效果
            try:
                toast.attributes("-alpha", 0.95)
            except tk.TclError:
                pass

            # 外层容器：带边框色
            outer = tk.Frame(toast, bg="#2E7D32", bd=1)
            outer.pack()

            inner = tk.Frame(outer, bg="#E8F5E9", padx=px(18), pady=px(12))
            inner.pack()

            tk.Label(inner, text=title, font=font_scaled("微软雅黑", 12, "bold"),
                     bg="#E8F5E9", fg="#1B5E20").pack(anchor="w")
            tk.Label(inner, text=message, font=font_scaled("微软雅黑", 10),
                     bg="#E8F5E9", fg="#2E7D32", justify="left").pack(anchor="w", pady=(px(4), 0))

            # 计算屏幕右下角位置
            toast.update_idletasks()
            w = toast.winfo_reqwidth()
            h = toast.winfo_reqheight()
            sw = toast.winfo_screenwidth()
            sh = toast.winfo_screenheight()
            x = sw - w - px(30)
            y = sh - h - px(60)
            toast.geometry(f"+{x}+{y}")

            # duration_ms 毫秒后自动销毁
            def _auto_close():
                try:
                    if toast.winfo_exists():
                        toast.destroy()
                except tk.TclError:
                    pass

            toast.after(duration_ms, _auto_close)
        except Exception:
            # 兜底：失败了至少在状态栏显示
            self._set_status(f"{title}: {message.split(chr(10))[0]}")

    def _is_admin(self):
        return self.boot_detector.is_admin()

    def _get_bcd_args(self, force_mount=False):
        """获取BCD参数，根据引导环境自动返回正确的/store参数"""
        return self.boot_detector.get_bcd_args(force_mount)

    def _get_boot_manager(self):
        """获取BootManager实例"""
        if self._boot_mgr_instance is not None:
            return self._boot_mgr_instance
        
        if self._boot_mgr_callback:
            self._boot_mgr_instance = self._boot_mgr_callback()
            return self._boot_mgr_instance
        
        return None

    def _get_boot_add_menu(self):
        """获取BootAddMenu实例（通过BootManager）"""
        boot_mgr = self._get_boot_manager()
        if boot_mgr and hasattr(boot_mgr, 'boot_add_menu'):
            return boot_mgr.boot_add_menu
        return None

    def _extract_iso_boot_wim(self, iso_path):
        """使用 7z 从 ISO 中提取 boot.wim"""
        self._set_progress(10, "正在提取ISO中的boot.wim...")
        temp_dir = tempfile.mkdtemp()
        try:
            iso_path = os.path.abspath(iso_path)
            self._log(f"正在从ISO提取boot.wim: {iso_path}")

            sevenz_exe = self.sevenz_exe
            if not sevenz_exe or not os.path.exists(sevenz_exe):
                sevenz_exe = "7z.exe"

            self._set_progress(20, "正在使用7z提取...")
            self._log(f"使用7z提取: {sevenz_exe}")

            boot_wim_dest = os.path.join(temp_dir, "boot.wim")

            cmd = [sevenz_exe, "e", iso_path, "sources\\boot.wim", f"-o{temp_dir}", "-y"]
            self._log(f"执行命令: {' '.join(cmd)}")
            ok, out = self._run_get(cmd, "提取sources/boot.wim")

            if not ok or not os.path.exists(boot_wim_dest):
                cmd = [sevenz_exe, "e", iso_path, "boot.wim", f"-o{temp_dir}", "-y"]
                self._log(f"执行命令: {' '.join(cmd)}")
                ok, out = self._run_get(cmd, "提取boot.wim")

            if ok and os.path.exists(boot_wim_dest):
                self._set_progress(30, "提取成功")
                self._log(f"boot.wim已提取到: {boot_wim_dest}")
                return boot_wim_dest
            else:
                self._log("错误: 在ISO中未找到boot.wim")
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
                return None
        except Exception as e:
            self._log(f"提取ISO失败: {e}")
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
            return None

    def _copy_wim_to_boot_dir(self, wim_path, dest_dir):
        """复制WIM到引导目录（委托给 boot_utils 共享逻辑 + Toast提示）

        说明：
        - 核心逻辑（创建目录、删旧文件、检查空间、复制）由 boot_utils.copy_wim_to_dir 统一处理
        - 本方法仅负责 UI 反馈（进度、Toast、状态栏）
        """
        self._set_progress(40, "正在复制WIM到引导目录...")

        ok, result = self.boot_detector.copy_wim_to_dir(wim_path, dest_dir, log_fn=self._log)

        if ok:
            self._set_progress(50, "复制完成")
            return result

        # 根据错误类型给出不同 Toast 提示
        err_msg = result
        if "空间不足" in err_msg:
            self._set_status("磁盘空间不足")
            self._show_toast(
                "✗ 磁盘空间不足",
                f"{err_msg}\n\n请取消勾选「复制PE包到」选项，或选择其他有足够空间的目标路径。",
            )
        elif "权限不足" in err_msg:
            self._log(f"复制WIM失败，权限不足: {err_msg}")
            if not self._is_admin():
                self._log("提示: 当前为普通用户模式，如果复制到C盘失败，请尝试使用D盘路径")
            self._set_status(f"复制失败: 权限不足 - {os.path.basename(dest_dir)}")
            self._show_toast(
                "✗ 权限不足",
                f"{err_msg}\n\n请尝试：\n1. 手动创建目录 {dest_dir}\n2. 或选择其他路径（如 D:\\IsBoot）",
            )
        else:
            self._log(f"复制WIM失败: {err_msg}")
            self._set_status(f"复制失败: {err_msg}")
            self._show_toast("✗ 复制失败", f"无法复制WIM到引导分区\n\n错误: {err_msg}")

        return None

    def _find_boot_sdi_source(self):
        """查找boot.sdi源文件路径"""
        return self.boot_detector.find_boot_sdi_source(self.base_dir, self.data_dir)

    def _ensure_ramdisk_options(self):
        """确保 {ramdiskoptions} 存在并正确配置 boot.sdi"""
        return self.boot_detector.ensure_ramdisk_options(self.base_dir, self.data_dir)
    
    def _detect_boot_environment(self):
        """检测当前引导环境：区分PE/原生Windows + UEFI/BIOS"""
        return self.boot_detector.detect_boot_environment()
    
    def _check_efi_partition(self, drive_letter):
        """检查指定盘符的系统是否有UEFI引导分区"""
        return self.boot_detector.check_efi_partition(drive_letter)
    
    def _find_offline_system_drive(self):
        """在 PE 环境中查找真正的离线系统盘（排除X盘等虚拟盘）"""
        return self.boot_detector.find_offline_system_drive()
    
    def _read_offline_registry(self, drive, value_name):
        """读取离线系统的注册表值"""
        return self.boot_detector.read_offline_registry(drive, value_name)
    
    def _mount_efi_partition(self):
        """挂载 EFI 系统分区并返回挂载点（固定 Z 盘，带全局缓存）"""
        return self.boot_detector.ensure_efi_mounted()
    
    def _unmount_efi_partition(self):
        """卸载 Z: 盘（ESP分区）"""
        return self.boot_detector.unmount_efi_partition()

    def _execute(self):
        file_source = self.file_source.get()
        menu_name = self.menu_name.get().strip()

        if not file_source or not os.path.exists(file_source):
            messagebox.showerror("错误", "请选择有效的ISO或WIM文件", parent=self.parent.master)
            return
        if not menu_name:
            messagebox.showerror("错误", "请输入菜单名称", parent=self.parent.master)
            return
        if not self._is_admin():
            self._log("警告: 当前为普通用户模式，添加引导可能需要管理员权限")
            if not messagebox.askyesno("权限警告", "当前为普通用户模式，添加引导可能需要管理员权限。\n\n是否继续？", parent=self.parent.master):
                return

        self._set_progress(0, "开始执行...")
        wim_path = None
        temp_dir = None
        is_iso_source = file_source.lower().endswith('.iso')

        try:
            # 步骤1: 处理文件来源
            if is_iso_source:
                # ISO格式：提取sources/boot.wim
                self._log("检测到ISO文件，正在提取boot.wim...")
                wim_path = self._extract_iso_boot_wim(file_source)
                if not wim_path:
                    self._set_status("提取ISO失败")
                    messagebox.showerror("失败", "无法从ISO中提取boot.wim", parent=self.parent.master)
                    return
                temp_dir = os.path.dirname(wim_path)
            elif file_source.lower().endswith('.wim'):
                # WIM格式：直接使用
                self._log("检测到WIM文件，直接使用")
                wim_path = file_source
            else:
                messagebox.showerror("错误", "不支持的文件格式，请选择ISO或WIM文件", parent=self.parent.master)
                return

            # 步骤2: 根据引导模式确定引导分区路径
            env_info = self._detect_boot_environment()
            boot_mode = env_info['boot_mode']
            has_efi = env_info['has_efi']
            target_drive = env_info['target_drive']
            
            # 确定引导文件存放目录
            if boot_mode == 'uefi' and has_efi:
                # UEFI模式：挂载ESP分区到Z:盘
                efi_mount = self._mount_efi_partition()
                if efi_mount:
                    boot_partition_root = efi_mount.rstrip("\\") + "\\"
                    isboot_dir = os.path.join(boot_partition_root, "IsBoot")
                    self._log(f"UEFI模式，引导文件目录: {isboot_dir}")
                else:
                    self._log("错误: 无法挂载ESP分区")
                    messagebox.showerror("失败", "无法挂载ESP分区", parent=self.parent.master)
                    return
            else:
                # BIOS模式：使用系统盘
                boot_partition_root = target_drive.rstrip("\\") + "\\"
                isboot_dir = os.path.join(boot_partition_root, "IsBoot")
                self._log(f"BIOS模式，引导文件目录: {isboot_dir}")
            
            # 步骤3: 处理文件复制逻辑
            need_copy = False
            copied_wim_path = None
            
            if is_iso_source:
                # ISO格式：始终需要复制到引导分区/IsBoot/目录
                need_copy = True
                self._log("ISO格式PE，需要提取并复制boot.wim到引导分区")
            elif self.copy_pe.get():
                # WIM格式：勾选了复制PE包选项
                need_copy = True
                self._log("WIM文件，已勾选复制PE包选项")
            else:
                # WIM格式：未勾选复制，仅添加引导项
                self._log("WIM文件，未勾选复制，仅添加引导项")
            
            if need_copy:
                # 统一使用 _copy_wim_to_boot_dir（含路径规范化、磁盘空间检查、
                # shutil.copy2 失败时回退 cmd copy /Y、权限友好提示）
                # 之前的 inline 逻辑缺少这些回退，导致 PE 下从光驱复制到
                # 系统盘 C:\IsBoot\ 时可能抛 [WinError 5] 拒绝访问
                copied_wim_path = self._copy_wim_to_boot_dir(wim_path, isboot_dir)
                if not copied_wim_path:
                    self._set_status("复制WIM失败")
                    return

                # 更新wim_path为复制后的路径
                wim_path = copied_wim_path
                # 清理临时目录（如果是ISO提取的）
                if temp_dir and os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                        self._log(f"已清理临时目录: {temp_dir}")
                    except:
                        pass
                    temp_dir = None
            
            # 步骤4: 添加引导项到BCD
            boot_add_menu = self._get_boot_add_menu()
            if not boot_add_menu:
                self._log("错误: 无法获取BootAddMenu实例")
                messagebox.showerror("错误", "无法获取引导添加模块", parent=self.parent.master)
                return

            add_to_menu = self.boot_mode.get() == "add"
            success, result = boot_add_menu.add_wim_entry(wim_path, menu_name, add_to_menu=add_to_menu)

            if not success:
                self._log(f"添加引导项失败: {result}")
                messagebox.showerror("失败", f"添加引导项失败: {result}", parent=self.parent.master)
                return

            guid = result

            if add_to_menu:
                self._set_progress(100, "执行完成")
                msg = f"引导项添加成功！\n\n名称: {menu_name}\nGUID: {guid}\n文件: {os.path.basename(wim_path)}"
                if self.restart_after.get():
                    msg += "\n\n即将重启系统..."
                    if messagebox.askyesno("确认重启", msg + "\n\n确定要现在重启吗？", parent=self.parent.master):
                        self._run(["shutdown", "/r", "/t", "0"], "重启系统")
                else:
                    self._set_status(f"引导项添加成功: {menu_name}")
                    self._show_toast("✓ 引导项添加成功", msg)
            else:
                # 临时测试模式：设置单次启动
                self._set_progress(80, "正在设置单次启动...")
                self._run(["bcdedit", "/bootsequence", guid], "设置单次启动序列")
                self._set_progress(100, "临时测试模式设置完成")
                msg = (f"临时测试模式设置成功！\n\n"
                       f"名称: {menu_name}\n"
                       f"GUID: {guid}\n\n"
                       f"下次启动将自动进入该系统（仅生效一次），\n"
                       f"重启后自动恢复原默认启动项。\n"
                       f"该引导项不在启动菜单中显示。")
                if self.restart_after.get():
                    msg += "\n\n即将重启系统..."
                    if messagebox.askyesno("确认重启", msg + "\n\n确定要现在重启吗？", parent=self.parent.master):
                        self._run(["shutdown", "/r", "/t", "0"], "重启系统")
                else:
                    self._set_status(f"临时测试模式设置成功: {menu_name}")
                    self._show_toast("✓ 临时测试模式设置成功", msg)

        except Exception as e:
            self._log(f"执行失败: {e}")
            self._set_status("执行失败")
            messagebox.showerror("失败", f"执行失败: {e}", parent=self.parent.master)
        finally:
            # 清理临时目录
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass

