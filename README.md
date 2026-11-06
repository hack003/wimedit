# 映像编辑辅助工具（WIM Tool）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D4.svg)](https://www.microsoft.com/windows)
[![Version](https://img.shields.io/badge/Version-1.0.3.26-green.svg)](#)

**映像编辑辅助工具** 是一款面向 Windows 系统维护人员的小型工具集，聚焦 WIM 映像的日常编辑处理，并附带 PE 启动测试与 BCD 引导管理功能。基于 **Python 3 + tkinter** 开发，内置 DISM、wimlib、7-Zip 等组件，打包为单文件 exe，免安装、开箱即用。

国内项目地址：https://gitee.com/hack003/wim-tools

---

## ✨ 核心功能

| 模块 | 说明 |
|------|------|
| 💿 **镜像编辑** | 挂载 / 保存卸载 / 放弃卸载 / 清理卸载 WIM 映像，支持多索引切换、镜像优化、镜像信息读写 |
| 🧪 **启动测试** | 把 PE 的 boot.wim 添加到启动菜单，支持临时测试一次（不进菜单）、复制 PE 包到指定分区 |
| 🧭 **引导管理** | 枚举 / 编辑 / 删除 BCD 引导项，设置默认启动项，一键重置与修复引导 |
| 📋 **日志面板** | 四级别（ERROR / WARNING / INFO / DEBUG）彩色滑动条，级别可热切换、日志可回刷、可复制清空 |
| 🔄 **在线更新** | 启动时可检查新版本，支持下载并自动替换运行中的程序 |

---

## 🛠 技术栈

- **语言**：Python 3（标准库 + tkinter，无第三方依赖）
- **界面**：tkinter / ttk，自研 DPI 缩放工具（`dpi_utils.py`），支持 100% ~ 200% 高分屏
- **映像引擎**：DISM（挂载 / 卸载 / 属性）+ wimlib-imagex（info / optimize / 属性修改）
- **解包引擎**：7-Zip（从 ISO 中提取 boot.wim）
- **引导引擎**：bcdedit / bcdboot / mountvol / diskpart 系统命令
- **打包**：PyInstaller 单文件打包，内嵌 manifest（管理员权限 + 通用控件 v6 + 长路径支持）

---

## 📦 系统要求

- **操作系统**：Windows 10 / 11（x64，含 PE 环境）
- **权限**：必须以**管理员身份**运行（DISM 挂载、BCD 编辑、ESP 挂载均需管理员权限）
- **磁盘空间**：挂载 WIM 时默认使用 `D:\_WIM_Mount\<映像文件名>`，请确保 D 盘有足够空间
- **运行时**：使用发布版 exe 无需安装 Python；从源码运行需 Python 3.x

---

## 🚀 快速开始

### 方式一：使用发布版（推荐）

前往 **[Gitee Releases](https://gitee.com/hack003/wim-tools/releases)** 下载最新版 `WIMTool.exe`，双击运行即可（会自动请求管理员权限）。

程序为单文件分发，`data` 目录已打包进 exe，运行时自动解压到临时目录。

### 方式二：从源码运行

```bash
git clone https://gitee.com/hack003/wim-tools.git
cd wim-tools
python wim_tool.py
```

> 源码运行时请保持根目录下 `wimtool/` 的相对位置不变，程序按相对路径加载 `wimtool/src`、`wimtool/data` 与 `wimtool/resources` 资源。

---

## 📖 功能模块详解

### 1. 镜像编辑 Tab

**文件选择**：支持手动输入路径、`浏览` 选择、`搜索` 自动扫描磁盘查找 `.wim` / `.esd` / `.swm` 文件。

**挂载操作**：

| 按钮 | 行为 |
|------|------|
| 镜像挂载 | `DISM /Mount-Wim` 挂载到 `D:\_WIM_Mount\<映像名>`，自动清理残留挂载点 |
| 保存卸载 | 先 `/Commit-Wim` 保存变更，再 `/Unmount-Wim /Commit` 提交卸载 |
| 放弃卸载 | `/Unmount-Wim` 不提交，丢弃所有修改 |
| 清理卸载 | 强制卸载所有挂载并清理残留目录 |
| 恢复挂载 | 读取 `DISM /Get-MountedWimInfo`，把已存在的挂载恢复到列表 |

**挂载列表**：显示序号、挂载目录、映像文件、卷号、状态，双击可快速定位。

**镜像信息展示和修改**：

- 索引下拉框切换卷，自动读取并显示架构 `[x64]`、系统版本号、语言、Edition、Build 等信息
- 可编辑字段：显示名称、显示描述、映像名称、映像描述
- 操作流程：`信息处理` 进入编辑模式 → 修改字段 → `提交` 写回（`--image-property DISPLAYNAME / DISPLAYDESCRIPTION / NAME / DESCRIPTION`）→ `取消` 还原

**镜像优化**：调用 `wimlib-imagex optimize` 对 WIM 重新压缩去重，减小体积。

### 2. 启动测试 Tab

将 PE 映像加入启动菜单，重启即可进入 PE 环境：

- **启动模式**：`添加到启动菜单`（永久菜单项）/ `临时测试一次（不加入菜单）`
- **等待时间**：3 / 5 / 10 / 15 / 30 秒
- **菜单语言**：zh-CN / en-US / zh-TW / ja-JP
- **传统菜单**：兼容旧版字符菜单样式
- **菜单名称**：可自定义，内置常用预设（Windows 10 PE / Windows 11 PE / 微PE工具箱 / 系统维护等）
- **复制 PE 包到**：把 boot.wim / ISO 复制到引导分区 `IsBoot` 目录（UEFI 下为挂载后的 ESP，默认 `Z:\IsBoot`）
- **文件来源**：支持搜索或浏览选择 `.wim` / `.iso`；选择 ISO 时自动用 7-Zip 提取其中的 `boot.wim`
- **IsBoot 目录列表**：内置文件列表（文件名 / 大小 / 修改时间），右键可直接删除，无需进资源管理器
- **完成后重启**：勾选后执行完自动重启验证效果

> 添加引导项时会自动配置 `{ramdiskoptions}` 与 `boot.sdi`：先定位引导分区（UEFI = ESP，BIOS = 活动分区），检查 BCD 现有配置，缺失时从 `data/Boot` 或引导分区复制 `boot.sdi` 并写入 `ramdisksdidevice=boot`、`ramdisksdipath=\Boot\boot.sdi`。

### 3. 引导管理 Tab

- **引导项选择**：下拉列出所有 BCD 条目，可切换 `全部` / `有效`（仅启动加载器类条目）过滤
- **属性值表格**：展示当前条目的全部 BCD 属性（属性名 / 值），支持双击行内编辑、下拉选择、右键删除属性字段
- **删除**：`bcdedit /delete <GUID> /cleanup`
- **设为默认**：`bcdedit /default <GUID>`
- **重置**：备份 BCD（生成 `.bak`）后删除，配合修复引导重建
- **修复引导**：`bcdboot <系统盘>:\Windows /s <引导盘>: [/f UEFI] /l zh-CN` 完整重装启动文件
- **分区选择对话框**：可手动指定引导分区与系统分区，并勾选目标系统是否为 UEFI

**环境自动识别**：

- UEFI：`mountvol /L` 快速筛选 + `mountvol Z: /S` 挂载 ESP（全程缓存，两个 Tab 共用一次挂载）
- BIOS：直接使用系统盘引导路径
- PE 环境：自动查找离线系统盘符并读取离线注册表判断固件类型
- 程序退出时统一卸载 ESP 分区

### 4. 关于软件 / 日志 / 更新

- **关于软件**：显示软件名称、版本号、联系方式，内置免责声明，并提供 `检查更新` 按钮
- **日志面板**：底部 `日志` 按钮切换日志视图；顶部滑动条选择级别（ERROR / WARNING / INFO / DEBUG），切换后自动回刷历史日志；支持右键复制、全选、清空
- **日志配置**：`resources/log_config.ini` 可为各模块（mount / unmount / optimize / info / system）单独设置级别
- **在线更新**：直接读取 Gitee Releases（`tag_name` 作为版本号、`body` 作为更新说明、`assets` 中的 exe 作为下载地址），下载新 exe 后由临时脚本替换并重启

---

## 📂 目录结构

```
code-映像编辑辅助工具-v1.0.3.26/
├── wim_tool.py                  # 主入口：窗口、Tab 容器、日志面板、横幅通知、关于页
├── build.py                     # PyInstaller 单文件打包脚本（自动递增版本号）
├── build.bat                    # 打包入口（双击运行，可选）
├── wimtool/                     # 源码与资源根目录
│   ├── src/
│   │   ├── wim_editor.py        # 镜像编辑模块（DISM 挂载 / wimlib 优化与属性）
│   │   ├── boot_test.py         # 启动测试模块（PE 加入启动菜单 / ISO 提取 / IsBoot 管理）
│   │   ├── boot_manager.py      # 引导管理模块（BCD 枚举 / 编辑 / 删除 / 修复）
│   │   ├── boot_add_menu.py     # 添加引导菜单对话框（bcdedit 建项 + ramdisk 配置）
│   │   ├── boot_utils.py        # 引导环境检测、ESP 挂载、离线系统识别、boot.sdi 处理
│   │   ├── file_searcher.py     # 通用文件搜索对话框（按盘符 + 深度扫描）
│   │   ├── logger_utils.py      # 统一日志管理（四级 + 模块级覆盖 + 缓冲回刷）
│   │   ├── dpi_utils.py         # DPI 缩放工具（px / font / geometry 统一换算）
│   │   ├── update.py            # 在线更新（Gitee Releases 版本检查 / 下载 / 自动替换）
│   │   └── app_version.py       # 统一版本号（改版本号只需改这一处）
│   ├── data/                    # 内置组件（打包进 exe）
│   │   ├── DISM/                # DISM 及依赖库 + zh-CN 语言资源
│   │   ├── Wimlib/              # wimlib-imagex.exe + libwim-15.dll
│   │   ├── 7Z/                  # 7z.exe + 7z.dll
│   │   └── Boot/                # boot.sdi / bootmgr / bootmgfw_x64.efi / 字体等启动文件
│   └── resources/
│       ├── log_config.ini       # 日志级别配置
│       ├── wim.ico              # 程序图标
│       └── wimtool.manifest     # 管理员权限 + 系统兼容性清单
├── README.md
├── LICENSE
└── .gitignore
```

---

## 🔧 从源码打包

双击根目录 `build.bat`（或执行 `python build.py`）即可打包：

1. 自动把 `wimtool/src/app_version.py` 中版本号末位 +1
2. 清理 `build_output/` 并生成 `version.txt`（写入文件属性中的版本 / 版权 / 编译时间）
3. 收集 `wimtool/data/` 与 `wimtool/resources/wim.ico` 作为内嵌资源，生成 `wim_tool.spec`
4. 调用 PyInstaller 输出单文件 `D:\WIMTool.exe`
5. 自动清理 `build_output/work` 与根目录、`wimtool/src` 下的 `__pycache__`

**打包依赖**：`pip install pyinstaller`（仅打包时需要，运行不需要）。

**发布与更新**：打包完成后把 `D:\WIMTool.exe` 作为附件上传到 Gitee Releases，发布标签写成版本号（如 `v1.0.3.27`），发布说明填写更新内容。程序端的 `检查更新` 会直接读取该发布，标签号即版本号、说明即更新日志、附件即下载地址。

---

## ❓ 常见问题

**Q：ESP 分区挂载到 Z: 盘后，资源管理器打不开，提示"位置不可用"？**
这是 Windows 对 `mountvol` 挂载卷的权限隔离机制，属系统限制而非工具问题。程序已内置 `IsBoot` 目录文件列表，可直接在界面中查看和删除文件，无需进入资源管理器。

**Q：提示"请以管理员身份运行"？**
DISM 挂载、BCD 读写、ESP 挂载都需要管理员权限。发布版 exe 的 manifest 已声明 `requireAdministrator`，双击即提权；源码运行时请用管理员权限的终端启动。

**Q：挂载失败或挂载目录残留？**
点击 `清理卸载` 强制卸载全部挂载并清理 `D:\_WIM_Mount` 下的残留目录；若仍失败，可用 `DISM /Cleanup-Wim` 或重启后重试。

**Q：日志看不到进度信息？**
日志默认级别为 `WARNING`。把日志面板滑动条拨到 `DEBUG`，或修改 `resources/log_config.ini` 中对应模块级别。

---

## 🙏 致谢

- **秋刀鱼 WIT（WIT）** —— 本工具的开发初衷源于对 WIT 映像编辑功能的日常依赖，谨向其开发者致谢
- **wimlib** —— 提供高效的 WIM 读取、优化与属性修改能力
- **7-Zip** —— 提供 ISO 解包能力
- **Microsoft DISM / bcdedit / bcdboot** —— 提供映像挂载与引导管理底层能力

---

## 📄 许可证与免责声明

本项目基于 [MIT License](LICENSE) 开源。

```
Copyright (c) 2026 XuGuihong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**使用须知**：

1. 本软件处于持续开发阶段，可能存在未知 Bug，请谨慎使用。
2. 使用前请务必备份重要数据，以防数据丢失或损坏。
3. 本软件仅供学习和研究使用，使用者应自行承担使用风险。
4. 开发者不对软件的适用性、可靠性、安全性作任何明示或暗示的保证。
5. 因使用本软件导致的任何数据丢失、系统损坏或其他损失，开发者不承担任何责任。
6. 使用本软件即表示您已阅读并同意上述全部内容。

---

**联系方式**：hack003@163.com