import os

# 测试 os.path.splitdrive 返回值
test_paths = [
    r"D:\test\boot.wim",
    r"E:\EFI\Microsoft\Boot\boot.sdi",
    r"E:",
    r"E:\\",
    r"C:\boot.sdi",
]
for p in test_paths:
    drive, rel = os.path.splitdrive(p)
    print(f"{p!r} -> drive={drive!r}, rel={rel!r}")

# 测试 _split_drive_abs 等价代码
print("\n=== _split_drive_abs 行为 ===")
for p in test_paths:
    drive, rel = os.path.splitdrive(os.path.normpath(p))
    if not rel.startswith("\\"):
        rel = "\\" + rel
    print(f"{p!r} -> drive={drive!r}, rel={rel!r}")

# 测试 rel_path.lstrip("\\") 后再补一个 \
print("\n=== rel_path 规范化测试 ===")
for p in test_paths:
    boot_drive, rel_path = os.path.splitdrive(p)
    rel_path = os.path.normpath(rel_path or "\\boot.sdi")
    rel_path = "\\" + rel_path.lstrip("\\")
    print(f"{p!r} -> boot_drive={boot_drive!r}, rel_path={rel_path!r}")
    # 看 ramdisksdidevice 如何构造
    dev = f"partition={boot_drive.rstrip(':')}:"
    print(f"    ramdisksdidevice -> {dev!r}")

# 测试 ramdisk=[盘符]... 的格式
print("\n=== ramdisk 设备字符串格式 ===")
for p in test_paths:
    drive, rel = os.path.splitdrive(os.path.normpath(p))
    if not rel.startswith("\\"):
        rel = "\\" + rel
    device_str = f"ramdisk=[{drive}]{rel},{{ramdiskoptions}}"
    print(f"{p!r} -> {device_str!r}")