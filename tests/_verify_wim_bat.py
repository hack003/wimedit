# -*- coding: utf-8 -*-
import os
import sys
import time
import shutil

sys.path.insert(0, r"d:\code\映像编辑辅助工具")
from update import _generate_updater_script

TEMP = os.environ.get("TEMP")
temp_dir = os.path.join(TEMP, "_wim_test_update_" + str(int(time.time())))
os.makedirs(temp_dir, exist_ok=True)
new_exe = os.path.join(temp_dir, "映像编辑辅助工具.new.exe")
old_exe = os.path.join(r"d:\code\映像编辑辅助工具", "映像编辑辅助工具.exe")

bat = _generate_updater_script(new_exe, old_exe, temp_dir)
print("BAT 路径:", bat)
print()
print("=" * 70)
with open(bat, "r", encoding="utf-8") as f:
    content = f.read()
    print(content)
print("=" * 70)

checks = [
    ("包含 copy /y (非 move)", "copy /y" in content and "move /y" not in content),
    ("包含 explorer.exe 启动", "explorer.exe" in content),
    ("不包含旧的 start \"\"", 'start ""' not in content),
    ("包含 _MEI 清理", "_MEI" in content),
    ("包含 dir 强制刷新", "dir " in content),
    ("包含足够的 timeout", content.count("timeout") >= 5),
]
print()
all_ok = True
for desc, ok in checks:
    status = "✅" if ok else "❌"
    print("  " + status + " " + desc)
    if not ok:
        all_ok = False

if all_ok:
    print("\n✅ BAT 脚本内容正确")
else:
    print("\n❌ 有问题")

try:
    os.remove(bat)
except Exception:
    pass
try:
    shutil.rmtree(temp_dir, ignore_errors=True)
except Exception:
    pass