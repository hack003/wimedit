# -*- coding: utf-8 -*-
"""文件搜索模块 - 统一的ISO/WIM文件搜索对话框"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import threading
from dpi_utils import px, font_scaled


class FileSearchDialog:
    """文件搜索对话框"""
    
    def __init__(self, parent, icon_path=None, title="搜索文件", file_types=None, default_drives=None, default_depth=3):
        """
        初始化搜索对话框
        
        Args:
            parent: 父窗口
            icon_path: 图标文件路径
            title: 对话框标题
            file_types: 文件类型配置，格式: {'.wim': 'WIM文件', '.iso': 'ISO文件'} 或 '全部'
            default_drives: 默认勾选的盘符列表，如 ['C:\\', 'D:\\']
            default_depth: 默认搜索深度
        """
        self.parent = parent
        self.icon_path = icon_path
        self.title = title
        self.default_drives = default_drives or ['D:\\']
        self.default_depth = default_depth
        self.selected_file = None
        
        # 文件类型配置
        if file_types is None:
            self.file_types = {'.wim': 'WIM文件', '.iso': 'ISO文件'}
        else:
            self.file_types = file_types
        
        self._build_dialog()
    
    def _build_dialog(self):
        """构建搜索对话框UI（紧凑版，保证 DPI 下按钮始终可见）"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(self.title)
        self.dialog.geometry(f"{px(520)}x{px(400)}")
        self.dialog.minsize(px(400), px(280))
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

        # 为对话框内的 Treeview 配置 DPI 缩放样式（紧凑版）
        try:
            _fs_style = ttk.Style(self.dialog)
            _fs_style.configure(
                "FileSearcher.Treeview",
                font=font_scaled("Microsoft YaHei", 9),
                rowheight=px(20),
            )
            _fs_style.configure(
                "FileSearcher.Treeview.Heading",
                font=font_scaled("Microsoft YaHei", 9, "bold"),
                rowheight=px(24),
            )
        except Exception:
            pass

        if self.icon_path and os.path.exists(self.icon_path):
            for _i in range(5):
                try:
                    self.dialog.iconbitmap(self.icon_path)
                    break
                except Exception:
                    import time
                    time.sleep(1)

        # ====== 顶部搜索配置区（全部一行显示，紧凑布局） ======
        top_frame = ttk.LabelFrame(self.dialog, text="搜索配置", padding=px(3))
        top_frame.pack(fill=tk.X, padx=px(6), pady=(px(5), px(2)))

        # 整行：盘符 + 深度 + 文件类型 + 搜索按钮（同一行）
        row = ttk.Frame(top_frame)
        row.pack(fill=tk.X)

        ttk.Label(row, text="盘符:").pack(side=tk.LEFT, padx=(0, px(3)))
        self.drive_vars = {}
        for drive in ['C:\\', 'D:\\', 'E:\\', 'F:\\']:
            self.drive_vars[drive] = tk.BooleanVar(value=(drive in self.default_drives))
            ttk.Checkbutton(
                row, text=drive.replace('\\', ''), variable=self.drive_vars[drive]
            ).pack(side=tk.LEFT, padx=px(2))

        ttk.Label(row, text="深度:").pack(side=tk.LEFT, padx=(px(4), px(3)))
        self.depth_var = tk.StringVar(value=str(self.default_depth))
        depth_combo = ttk.Combobox(row, textvariable=self.depth_var, width=4, state="readonly")
        depth_combo['values'] = ['1', '2', '3', '4', '5']
        depth_combo.pack(side=tk.LEFT, padx=(0, px(4)))

        ttk.Label(row, text="类型:").pack(side=tk.LEFT, padx=(0, px(3)))
        self.file_type_var = tk.StringVar(
            value="全部" if len(self.file_types) > 1 else list(self.file_types.keys())[0]
        )
        type_values = list(self.file_types.keys()) + ['全部'] if len(self.file_types) > 1 else list(self.file_types.keys())
        file_type_combo = ttk.Combobox(row, textvariable=self.file_type_var, width=8, state="readonly")
        file_type_combo['values'] = type_values
        file_type_combo.pack(side=tk.LEFT, padx=(0, px(4)))

        self.search_btn = ttk.Button(row, text="搜索", command=self._do_search, width=8)
        self.search_btn.pack(side=tk.LEFT, padx=px(2))

        # ====== 进度条（紧凑） ======
        progress_frame = ttk.Frame(self.dialog)
        progress_frame.pack(fill=tk.X, padx=px(6), pady=px(2))

        self.progress_bar = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, mode='indeterminate')
        self.progress_bar.pack(fill=tk.X, expand=True)

        self.status_label = ttk.Label(progress_frame, text="", anchor=tk.CENTER)
        self.status_label.pack(fill=tk.X)

        # ====== 搜索结果 Treeview（高度跟随容器填充，不固定大行数） ======
        result_label = ttk.Label(self.dialog, text="搜索结果:")
        result_label.pack(anchor=tk.W, padx=px(6), pady=(px(2), 0))

        tree_frame = ttk.Frame(self.dialog)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=px(6), pady=px(2))

        columns = ("name", "dir", "mtime")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="FileSearcher.Treeview",
            height=6,
        )
        self.tree.heading("name", text="文件名")
        self.tree.heading("dir", text="来源目录")
        self.tree.heading("mtime", text="修改日期")
        self.tree.column("name", width=px(120), anchor=tk.W)
        self.tree.column("dir", width=px(180), anchor=tk.W)
        self.tree.column("mtime", width=px(80), anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda e: self._on_select())
        self.tree.bind("<Return>", lambda e: self._on_select())

        # ====== 底部按钮（紧凑 padding） ======
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill=tk.X, padx=px(6), pady=px(4))

        ttk.Button(btn_frame, text="确定", command=self._on_select, width=10).pack(side=tk.LEFT, padx=px(3))
        ttk.Button(btn_frame, text="取消", command=self.dialog.destroy, width=10).pack(side=tk.LEFT, padx=px(3))
        ttk.Button(btn_frame, text="浏览...", command=self._browse_file, width=10).pack(side=tk.LEFT, padx=px(3))

        self.cancel_flag = False
    
    def _browse_file(self):
        """浏览文件"""
        filetypes = []
        for ext, desc in self.file_types.items():
            filetypes.append((desc, f"*{ext}"))
        filetypes.append(("所有文件", "*.*"))
        
        f = filedialog.askopenfilename(
            title="选择文件",
            filetypes=filetypes
        )
        if f:
            self.selected_file = f
            self.dialog.destroy()
    
    def _on_select(self, event=None):
        """选择文件"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("警告", "请选择一个文件")
            return
        filepath = self.tree.item(sel[0], "values")[3]
        self.selected_file = filepath
        self.dialog.destroy()
    
    def _do_search(self):
        """执行搜索"""
        # 获取选中的盘符
        drives = [drive for drive, var in self.drive_vars.items() if var.get()]
        
        if not drives:
            messagebox.showwarning("警告", "请至少选择一个搜索路径")
            return
        
        # 获取搜索选项
        try:
            max_depth = int(self.depth_var.get())
        except ValueError:
            max_depth = 3
        
        file_type = self.file_type_var.get()
        
        # 禁用搜索按钮
        self.search_btn.config(state=tk.DISABLED)
        self.status_label.config(text="正在搜索文件...")
        self.progress_bar.start()
        self.cancel_flag = False
        
        # 启动搜索线程
        thread = threading.Thread(target=self._search_thread, args=(drives, max_depth, file_type), daemon=True)
        thread.start()
    
    def _search_thread(self, drives, max_depth, file_type):
        """搜索线程"""
        found_files = []
        
        for drive in drives:
            if self.cancel_flag:
                break
            if not os.path.exists(drive):
                continue
            
            self.dialog.after(0, lambda d=drive: self.status_label.config(text=f"正在搜索 {d}..."))
            self._search_dir(drive, max_depth, 0, found_files, file_type)
        
        # 更新UI
        if not self.cancel_flag:
            self.dialog.after(0, lambda: self._update_tree(found_files))
        else:
            self.dialog.after(0, lambda: self.search_btn.config(state=tk.NORMAL))
            self.dialog.after(0, lambda: self.progress_bar.stop())
            self.dialog.after(0, lambda: self.status_label.config(text="搜索已取消"))
    
    def _search_dir(self, root_dir, max_depth, current_depth, found_files, file_type):
        """递归搜索目录"""
        if current_depth >= max_depth or self.cancel_flag:
            return
        
        try:
            for item in os.listdir(root_dir):
                if self.cancel_flag:
                    return
                item_path = os.path.join(root_dir, item)
                if os.path.isfile(item_path):
                    # 检查文件类型
                    if file_type == "全部":
                        if not any(item.lower().endswith(ext) for ext in self.file_types.keys()):
                            continue
                    else:
                        if not item.lower().endswith(file_type):
                            continue
                    
                    # 获取文件信息
                    try:
                        stat = os.stat(item_path)
                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")
                    except:
                        mtime = "未知"
                    
                    found_files.append({
                        "path": item_path,
                        "name": item,
                        "dir": root_dir,
                        "mtime": mtime
                    })
                elif os.path.isdir(item_path):
                    try:
                        self._search_dir(item_path, max_depth, current_depth + 1, found_files, file_type)
                    except PermissionError:
                        pass
        except PermissionError:
            pass
    
    def _update_tree(self, found_files):
        """更新搜索结果列表"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        for file_info in sorted(found_files, key=lambda x: x["path"]):
            self.tree.insert("", tk.END, values=(
                file_info["name"],
                file_info["dir"],
                file_info["mtime"],
                file_info["path"]
            ))
        
        self.search_btn.config(state=tk.NORMAL)
        self.progress_bar.stop()
        status_text = f"搜索完成，找到 {len(found_files)} 个文件"
        self.status_label.config(text=status_text)
    
    def show(self):
        """显示对话框并返回选中的文件路径"""
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)
        self.dialog.wait_window()
        return self.selected_file
    
    def _on_close(self):
        """关闭对话框"""
        self.cancel_flag = True
        self.dialog.destroy()


def search_file(parent, icon_path=None, title="搜索文件", file_types=None, default_drives=None, default_depth=3):
    """
    便捷函数：显示文件搜索对话框
    
    Args:
        parent: 父窗口
        icon_path: 图标文件路径
        title: 对话框标题
        file_types: 文件类型配置
        default_drives: 默认勾选的盘符列表
        default_depth: 默认搜索深度
    
    Returns:
        选中的文件路径，如果取消则返回None
    """
    dialog = FileSearchDialog(
        parent,
        icon_path=icon_path,
        title=title,
        file_types=file_types,
        default_drives=default_drives,
        default_depth=default_depth
    )
    return dialog.show()