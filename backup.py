# -*- coding: utf-8 -*-
"""备份源代码脚本 - 双击运行即可按目录结构打包源码为 zip"""

import os
import re
import sys
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

from app_version import VERSION_STR

EXCLUDE_DIRS = {
    "build_output", "__pycache__", ".git", ".venv", "venv", "node_modules",
}
EXCLUDE_EXTENSIONS = {".pyc", ".pyo", ".exe", ".dll", ".so", ".o", ".zip", ".7z", ".rar"}
EXCLUDE_FILES = set()


def should_include(dirpath, filename):
    if filename in EXCLUDE_FILES or filename.startswith("._"):
        return False
    rel = os.path.relpath(dirpath, SCRIPT_DIR)
    top_dir = rel.split(os.sep)[0] if rel != "." else ""
    if top_dir == "data":
        return True
    ext = os.path.splitext(filename)[1].lower()
    if ext in EXCLUDE_EXTENSIONS:
        return False
    return True


def main():
    folder_name = os.path.basename(SCRIPT_DIR)
    # 从文件夹名 code-程序名称-v版本号 中提取程序名称
    m = re.match(r'^code-(.+?)-v\d+', folder_name)
    app_name = m.group(1) if m else folder_name
    zip_name = f"code-{app_name}-v{VERSION_STR}.zip"
    zip_path = os.path.join(SCRIPT_DIR, zip_name)

    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(SCRIPT_DIR):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for filename in filenames:
                if not should_include(dirpath, filename):
                    continue
                full_path = os.path.join(dirpath, filename)
                arc_name = os.path.relpath(full_path, SCRIPT_DIR)
                zf.write(full_path, arc_name)
                file_count += 1

    size_kb = os.path.getsize(zip_path) / 1024
    print(f"备份完成: {zip_name}")
    print(f"文件数: {file_count}, 大小: {size_kb:.1f} KB")
    print(f"路径: {zip_path}")


if __name__ == "__main__":
    main()
