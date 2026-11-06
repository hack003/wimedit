# -*- coding: utf-8 -*-
"""
WIM Tool 单文件打包脚本
使用 PyInstaller 打包为单文件 exe，包含 data 文件夹及所有依赖
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# 项目根目录（build.py 所在目录）
PROJECT_DIR = Path(__file__).parent.absolute()
BUILD_DIR = PROJECT_DIR / "build_output"
SPEC_FILE = BUILD_DIR / "wim_edit.spec"

# 源码与资源根目录
SOURCE_DIR = PROJECT_DIR / "wimedit"

# 输出目录设置为 D 盘
DIST_DIR = Path("D:/")

# 主入口脚本
MAIN_SCRIPT = PROJECT_DIR / "wim_edit.py"

# 需要打包的 data 文件夹
DATA_DIR = SOURCE_DIR / "data"

# 输出文件名
APP_NAME = "WIMEdit"

# Manifest 文件（请求管理员权限 + Windows 版本兼容声明 + 长路径支持 + 通用控件 v6 视觉样式）
MANIFEST_FILE = SOURCE_DIR / "resources" / "wimedit.manifest"

# 源码目录
SRC_DIR = SOURCE_DIR / "src"

# 版本信息（从 app_version.py 统一读取，改版本号请修改 app_version.py）
import runpy as _runpy
_app_ver_ns = _runpy.run_path(str(SRC_DIR / "app_version.py"))
VERSION = _app_ver_ns["VERSION"]
VERSION_STR = _app_ver_ns["VERSION_STR"]
APP_VERSION_FILE = SRC_DIR / "app_version.py"
del _runpy, _app_ver_ns

PRODUCT_NAME = "映像编辑辅助工具"
COMPANY_NAME = "XuGuihong"
COPYRIGHT = "Copyright © 2026 XuGuihong. All rights reserved."
INTERNAL_NAME = "WIMEdit"
ORIGINAL_FILENAME = "WIMEdit.exe"


def check_dependencies():
    """检查必要的依赖"""
    print("=" * 60)
    print("检查依赖...")
    print("=" * 60)
    
    try:
        import PyInstaller
        print(f"✓ PyInstaller 已安装: {PyInstaller.__version__}")
    except ImportError:
        print("✗ PyInstaller 未安装")
        print()
        print("请手动安装 PyInstaller:")
        print("  pip install pyinstaller")
        print()
        sys.exit(1)
    
    # 检查 data 文件夹
    if not DATA_DIR.exists():
        print(f"✗ data 文件夹不存在: {DATA_DIR}")
        sys.exit(1)
    
    print(f"✓ data 文件夹存在: {DATA_DIR}")
    
    # 检查主入口文件
    if not MAIN_SCRIPT.exists():
        print(f"✗ 主入口文件不存在: {MAIN_SCRIPT}")
        sys.exit(1)
    
    print(f"✓ 主入口文件存在: {MAIN_SCRIPT}")
    print()


def collect_data_files():
    """收集 data 文件夹中的所有文件"""
    data_files = []
    
    if not DATA_DIR.exists():
        print("警告: data 文件夹不存在")
        return data_files
    
    for root, dirs, files in os.walk(DATA_DIR):
        for file in files:
            file_path = Path(root) / file
            # 计算相对路径（相对于 data 文件夹）
            relative_path = file_path.relative_to(DATA_DIR)
            # 目标文件夹路径（在打包后的结构中）
            dest_folder = f"data/{relative_path.parent}"
            data_files.append((str(file_path), dest_folder))
    
    # 添加 wim.ico 到打包数据（放在根目录）
    icon_file = SOURCE_DIR / "resources" / "wim.ico"
    if icon_file.exists():
        data_files.append((str(icon_file), "."))
        print("✓ 已添加 wim.ico 到打包数据")
    
    print(f"共收集 {len(data_files)} 个数据文件")
    return data_files


def generate_spec():
    """生成 PyInstaller spec 文件"""
    print("=" * 60)
    print("生成 spec 文件...")
    print("=" * 60)
    
    data_files = collect_data_files()
    
    # 构建 datas 列表 - 使用正斜杠避免转义问题
    datas_str = ""
    if data_files:
        datas_items = []
        for src, dest in data_files:
            # 将 Windows 反斜杠转换为正斜杠，避免 Python 字符串转义问题
            src_posix = src.replace('\\', '/')
            dest_posix = dest.replace('\\', '/')
            datas_items.append(f"        (r'{src_posix}', r'{dest_posix}')")
        datas_str = ",\n".join(datas_items)
    
    # 检查 manifest 文件是否存在
    manifest_path = MANIFEST_FILE.as_posix() if MANIFEST_FILE.exists() else None
    
    # 生成 spec 文件内容
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
"""
WIM Tool PyInstaller 配置文件
自动生成，请勿手动修改
"""

import os
from pathlib import Path

block_cipher = None

# 数据文件列表
a = Analysis(
    ['{MAIN_SCRIPT.as_posix()}'],
    pathex=[r'{BUILD_DIR.as_posix()}', r'{SRC_DIR.as_posix()}'],
    binaries=[],
    datas=[
{datas_str}
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'wim_editor',
        'boot_manager',
        'boot_test',
        'file_searcher',
        'boot_utils',
        'boot_add_menu',
        'dpi_utils',
        'logger_utils',
        'update',
        'app_version',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        'unittest',
        'test',
        'idlelib',
        'turtledemo',
        'tkinter.test',
        'distutils',
        'ensurepip',
        'venv',
        'pydoc_data',
        'lib2to3',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{APP_NAME}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    manifest='{manifest_path}',
    version=r'{(BUILD_DIR / "version.txt").as_posix()}',
    codesign_identity=None,
    entitlements_file=None,
    icon=r'{(SOURCE_DIR / "resources" / "wim.ico").as_posix()}',
)
'''
    
    # 确保 build 目录存在
    BUILD_DIR.mkdir(exist_ok=True)
    
    # 写入 spec 文件
    with open(SPEC_FILE, 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print(f"✓ spec 文件已生成: {SPEC_FILE}")
    print()
    
    return SPEC_FILE


def generate_version_file():
    """生成版本信息文件"""
    from datetime import datetime
    build_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    version_path = BUILD_DIR / "version.txt"
    content = f'''# UTF-8
#
# For more details about fixed file info:
# https://docs.microsoft.com/en-us/windows/desktop/menurc/vs-fixedfileinfo

VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={VERSION},
    prodvers={VERSION},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'080404b0',
        [StringStruct(u'CompanyName', u'{COMPANY_NAME}'),
        StringStruct(u'FileDescription', u'编译：{build_time}'),
        StringStruct(u'FileVersion', u'{VERSION_STR}'),
        StringStruct(u'InternalName', u'{INTERNAL_NAME}'),
        StringStruct(u'LegalCopyright', u'{COPYRIGHT}'),
        StringStruct(u'OriginalFilename', u'{ORIGINAL_FILENAME}'),
        StringStruct(u'ProductName', u'{PRODUCT_NAME}'),
        StringStruct(u'ProductVersion', u'{VERSION_STR}'),
        StringStruct(u'BuildTime', u'{build_time}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
'''
    version_path.write_text(content, encoding="utf-8")
    print(f"✓ 已生成 version.txt (版本: {VERSION_STR}, 编译时间: {build_time})")


def build():
    """执行打包"""
    print("=" * 60)
    print("开始打包...")
    print("=" * 60)

    global VERSION, VERSION_STR
    print(f"当前版本号: {VERSION_STR}（如需修改请编辑 wimedit/src/app_version.py）")
    
    # 清理旧的构建文件
    if BUILD_DIR.exists():
        print("清理旧的构建文件...")
        shutil.rmtree(BUILD_DIR)
    
    BUILD_DIR.mkdir(exist_ok=True)
    
    # 生成版本信息文件（必须在清理 BUILD_DIR 之后，否则会被一起删除）
    generate_version_file()
    
    # 创建输出目录
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    print(f"输出目录: {DIST_DIR}")
    
    # 生成 spec 文件
    spec_file = generate_spec()
    
    # 执行 PyInstaller
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        str(spec_file),
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "work"),
        "--noconfirm",
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_DIR),
            check=True,
            capture_output=False
        )
        
        print()
        print("=" * 60)
        print("打包完成！")
        print("=" * 60)
        
        # 显示输出文件
        exe_path = DIST_DIR / f"{APP_NAME}.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"✓ 输出文件: {exe_path}")
            print(f"✓ 文件大小: {size_mb:.2f} MB")
        else:
            print("✗ 未找到输出文件")
        
        print()
        print("打包结构:")
        print(f"  {BUILD_DIR}/")
        print(f"  └── wim_edit.spec       <- PyInstaller 配置文件")
        print(f"  {DIST_DIR}/")
        print(f"  └── {APP_NAME}.exe      <- 单文件可执行程序")
        print()
        print("使用说明:")
        print(f"  1. 运行 {DIST_DIR}/{APP_NAME}.exe 即可")
        print(f"  2. data 文件夹已打包到 exe 内部")
        print(f"  3. 运行时会自动解压到临时目录")
        
        # 自动清理临时文件
        clean_temp_files()
        
    except subprocess.CalledProcessError as e:
        print()
        print("=" * 60)
        print("打包失败！")
        print("=" * 60)
        print(f"错误代码: {e.returncode}")
        # 即使打包失败，也尝试清理临时文件
        clean_temp_files()
        sys.exit(1)


def clean_temp_files():
    """清理临时文件（打包后自动执行）"""
    print()
    print("=" * 60)
    print("清理临时文件...")
    print("=" * 60)
    
    cleaned = False
    
    # 清理 build_output/work 目录
    work_dir = BUILD_DIR / "work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
        print(f"✓ 已删除临时工作目录: {work_dir}")
        cleaned = True
    
    # 清理 __pycache__ 目录（根目录 + 源码目录）
    for pycache_dir in (PROJECT_DIR / "__pycache__", SRC_DIR / "__pycache__"):
        if pycache_dir.exists():
            shutil.rmtree(pycache_dir)
            print(f"✓ 已删除 Python 缓存目录: {pycache_dir}")
            cleaned = True
    
    # 清理 spec 文件
    if SPEC_FILE.exists():
        SPEC_FILE.unlink()
        print(f"✓ 已删除 spec 文件: {SPEC_FILE}")
        cleaned = True
    
    # 清理 version.txt（打包时生成的版本信息文件）
    version_file = BUILD_DIR / "version.txt"
    if version_file.exists():
        version_file.unlink()
        print(f"✓ 已删除 version.txt: {version_file}")
        cleaned = True
    
    if not cleaned:
        print("没有需要清理的临时文件")
    else:
        print("✓ 临时文件清理完成")


def clean():
    """清理构建文件"""
    print("=" * 60)
    print("清理构建文件...")
    print("=" * 60)
    
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"✓ 已删除: {BUILD_DIR}")
    else:
        print("没有需要清理的构建文件")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="WIM Tool 打包脚本")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="仅清理构建文件"
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="跳过依赖检查"
    )
    
    args = parser.parse_args()
    
    if args.clean:
        clean()
        return
    
    if not args.no_check:
        check_dependencies()
    
    build()


if __name__ == "__main__":
    main()