import subprocess, os, re

r = subprocess.run(['bcdedit', '/enum', 'all'], capture_output=True, text=True, timeout=10)
out = r.stdout

print("=== bcdedit 输出中 WIM 引导项的 device/osdevice 属性 ===")
in_section = False
for line in out.split("\n"):
    s = line.strip()
    if s.startswith(("Windows Boot Loader", "Windows 启动加载器")):
        in_section = True
        print(f"\n[节] {s}")
        continue
    elif s.startswith(("Windows Boot Manager", "Windows 启动管理器",
                       "Firmware Boot Manager", "固件启动管理器")):
        in_section = False
        continue

    if in_section and s:
        if any(x in s.lower() for x in ("identifier", "标识符",
                                         "description", "描述",
                                         "device", "osdevice",
                                         "设备", "os设备", "os 设备")):
            print(f"  {s}")

# 测试 _match_wim_path 逻辑
print("\n=== 测试 _match_wim_path 逻辑 ===")

def match_wim_path(device_str, target_wim_norm):
    if not device_str or not target_wim_norm:
        return False
    device_lower = device_str.lower()
    if "ramdisk=" not in device_lower:
        return False
    try:
        after_eq = device_lower.split("=", 1)[1]
        before_comma = after_eq.split(",", 1)[0]
        if "]" in before_comma:
            pure_path = before_comma.split("]", 1)[1]
        else:
            pure_path = before_comma
        pure_path_norm = os.path.normpath(pure_path)
        if pure_path_norm.endswith(target_wim_norm) or target_wim_norm.endswith(pure_path_norm):
            return True
        target_basename = os.path.basename(target_wim_norm)
        current_basename = os.path.basename(pure_path_norm)
        if target_basename and target_basename == current_basename:
            return True
    except Exception:
        pass
    return False

# 构造测试用例
test_cases = [
    ("ramdisk=[boot]\\sources\\boot.wim,{ramdiskoptions}",
     "c:\\sources\\boot.wim",
     True, "同文件名应该匹配"),
    ("ramdisk=[C:]\\test\\winpe.wim,{ramdiskoptions}",
     "C:\\test\\winpe.wim",
     True, "完整路径应该匹配"),
    ("partition=C:",
     "C:\\test.wim",
     False, "非 ramdisk 不匹配"),
    ("ramdisk=[boot]\\sources\\boot.wim,{ramdiskoptions}",
     "D:\\other.wim",
     False, "不同文件名不匹配"),
]

for device_str, target_wim, expected, desc in test_cases:
    result = match_wim_path(device_str, os.path.normpath(target_wim).lower())
    status = "✓" if result == expected else "✗"
    print(f"  {status} {desc}: result={result}, expected={expected}")

print("\n测试完成")