import re
_GUID_RE = re.compile(r'\{[0-9a-fA-F-]+\}')

print("=== 伪标识符（应全部被拒绝）===")
pseudo = ['{default}', '{current}', '{bootmgr}', '{ramdiskoptions}', '{globalsettings}']
for p in pseudo:
    m = _GUID_RE.fullmatch(p)
    status = "MATCH!!BAD!!" if m else "rejected  OK"
    print(f"  {p:25s} -> {status}")

print("\n=== 真实 GUID（应全部匹配）===")
real = ['{9eafe6db-2472-11f1-967f-d0caece9856f}', '{7619dcc8-fafe-11d9-b411-000476eba25f}']
for p in real:
    m = _GUID_RE.fullmatch(p)
    status = "matched   OK" if m else "NO MATCH!!BAD!!"
    print(f"  {p} -> {status}")

print("\n=== 模拟 bcdedit /enum all 输出测试 ===")
fake_bcdedit = """
Windows Boot Manager
--------------------
identifier              {bootmgr}
device                  partition=Z:
description             Windows Boot Manager
locale                  zh-CN
inherit                 {globalsettings}
default                 {9eafe6db-2472-11f1-967f-d0caece9856f}
resumeobject            {9eafe6db-2472-11f1-967f-d0caece9856f}
displayorder            {9eafe6db-2472-11f1-967f-d0caece9856f}
toolsdisplayorder       {memdiag}
timeout                 30

Windows Boot Loader
-------------------
identifier              {9eafe6db-2472-11f1-967f-d0caece9856f}
device                  partition=C:
path                    \Windows\System32\winload.efi
description             Windows 11.24H2 Pro x64
locale                  zh-CN
inherit                 {bootloadersettings}
recoverysequence        {f2421270-2472-11f1-967f-d0caece9856f}
recoveryenabled         Yes
isolatedcontext         Yes
allowedinmemorysettings 0x15000075
osdevice                partition=C:
systemroot              \Windows
resumeobject            {9eafe6db-2472-11f1-967f-d0caece9856f}
nx                      OptIn
bootmenupolicy          Standard
quietboot               Yes

Windows Boot Loader
-------------------
identifier              {default}
device                  ramdisk=[Z:]\isboot\boot.wim,{ramdiskoptions}
path                    \Windows\System32\boot\winload.efi
description             WindowsPE
osdevice                ramdisk=[Z:]\isboot\boot.wim,{ramdiskoptions}
systemroot              \Windows
winpe                   Yes
detecthal               Yes

Windows Boot Loader
-------------------
identifier              {aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}
device                  ramdisk=[C:]\isboot\boot.wim,{ramdiskoptions}
path                    \Windows\System32\boot\winload.efi
description             WindowsPE
osdevice                ramdisk=[C:]\isboot\boot.wim,{ramdiskoptions}
systemroot              \Windows
winpe                   Yes
detecthal               Yes
"""

_BOOT_SECTION_TITLES_RE = re.compile(r"^Windows\s+(Boot|Memory)[\s\w]+$", re.IGNORECASE)
_BOOT_LOADER_RE = re.compile(r"Boot\s+Loader", re.IGNORECASE)
_PROP_IDENTIFIER = "identifier"
_PROP_DESCRIPTION = "description"

def _parse_property_value(line):
    parts = line.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""

menu_name = "WindowsPE"
current_guid = ""
in_valid_section = False
found = None

for line in fake_bcdedit.split("\n"):
    line = line.strip()
    if not line:
        continue
    if _BOOT_SECTION_TITLES_RE.search(line):
        in_valid_section = _BOOT_LOADER_RE.search(line) is not None
        current_guid = ""
        continue
    if not in_valid_section:
        continue
    if line.startswith(_PROP_IDENTIFIER):
        current_guid = _parse_property_value(line)
        if current_guid and not _GUID_RE.fullmatch(current_guid):
            current_guid = ""
    elif line.startswith(_PROP_DESCRIPTION):
        desc = _parse_property_value(line)
        if desc == menu_name and current_guid:
            found = current_guid
            break

print(f"  查找名称 '{menu_name}':")
print(f"    结果 GUID = {found}")
print(f"    {'PASS: 只匹配了真实 GUID' if found == '{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}' else 'FAIL: 可能匹配了伪标识符或漏匹配'}")
print()

print("=== 导入测试 ===")
try:
    from boot_manager import BootManager
    print("  BootManager import: OK")
except Exception as e:
    print(f"  BootManager import: FAIL - {e}")

try:
    from boot_add_menu import BootAddMenu
    print("  BootAddMenu import: OK")
except Exception as e:
    print(f"  BootAddMenu import: FAIL - {e}")

print("\n=== py_compile 语法检查 ===")
import py_compile
for f in ["boot_manager.py", "boot_add_menu.py"]:
    try:
        py_compile.compile(f, doraise=True)
        print(f"  {f}: SYNTAX OK")
    except py_compile.PyCompileError as e:
        print(f"  {f}: SYNTAX FAIL - {e}")