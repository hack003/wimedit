"""boot.sdi 路径匹配逻辑验证脚本"""
import os

# 模拟 _match_wim_path 的核心逻辑
def match_wim_path_simulation(device_str, target_wim_abs, boot_drive_letter=None):
    """
    简化版路径匹配：
    - 从 device_str 提取 [前缀] 和 relpath
    - 从 target_wim_abs 提取 drive 和 relpath
    - 严格比较：盘符匹配 + 路径完全相等
    """
    device_lower = device_str.lower()
    if "ramdisk=" not in device_lower:
        return False

    after_eq = device_lower.split("=", 1)[1]
    before_comma = after_eq.split(",", 1)[0]

    if "]" not in before_comma:
        return False

    prefix = before_comma.split("]", 1)[0].strip() + "]"
    bcd_relpath = before_comma.split("]", 1)[1]
    bcd_relpath_norm = os.path.normpath(bcd_relpath)

    # 注意：实际代码中 target_wim_norm 已经是 normpath + lower 过的
    # 这里模拟真实调用场景
    target_norm = os.path.normpath(target_wim_abs).lower()
    target_drive, target_rel = os.path.splitdrive(target_norm)
    target_rel_norm = os.path.normpath(target_rel)

    # 路径必须完全一致
    if bcd_relpath_norm != target_rel_norm:
        return False

    # 盘符映射
    if prefix == "[boot]":
        bcd_drive = boot_drive_letter.lower() if boot_drive_letter else ""
    else:
        bcd_drive = prefix.strip("[]").lower()

    target_drive_lower = target_drive.rstrip("\\").lower()

    if bcd_drive and bcd_drive == target_drive_lower:
        return True
    if not bcd_drive and prefix == "[boot]":
        # 无法获取盘符，放宽
        return True
    return False


# === 测试用例 ===
print("=" * 60)
print("【测试 1】同路径同盘符 —— 应匹配")
bcd1 = "ramdisk=[Z:]\\isboot\\boot.wim,{ramdiskoptions}"
target1 = "Z:\\isboot\\boot.wim"
r = match_wim_path_simulation(bcd1, target1, boot_drive_letter="Z:")
print(f"  BCD   : {bcd1}")
print(f"  Target: {target1}")
print(f"  结果  : {r}  {'✅ PASS' if r else '❌ FAIL'}")

print()
print("=" * 60)
print("【测试 2】不同盘符同路径 —— 不应匹配（这是旧代码的问题）")
bcd2 = "ramdisk=[Z:]\\isboot\\boot.wim,{ramdiskoptions}"
target2 = "D:\\isboot\\boot.wim"
r = match_wim_path_simulation(bcd2, target2, boot_drive_letter="Z:")
print(f"  BCD   : {bcd2}")
print(f"  Target: {target2}")
print(f"  结果  : {r}  {'✅ PASS' if not r else '❌ FAIL'}")

print()
print("=" * 60)
print("【测试 3】不同盘符同文件名（旧代码靠 basename 错误匹配）—— 不应匹配")
bcd3 = "ramdisk=[Z:]\\isboot\\boot.wim,{ramdiskoptions}"
target3 = "D:\\BOOT.wim"
r = match_wim_path_simulation(bcd3, target3, boot_drive_letter="Z:")
print(f"  BCD   : {bcd3}")
print(f"  Target: {target3}")
print(f"  结果  : {r}  {'✅ PASS' if not r else '❌ FAIL'}")

print()
print("=" * 60)
print("【测试 4】[boot] 前缀 + 位于引导分区 —— 应匹配")
bcd4 = "ramdisk=[boot]\\isboot\\boot.wim,{ramdiskoptions}"
target4 = "Z:\\isboot\\boot.wim"
r = match_wim_path_simulation(bcd4, target4, boot_drive_letter="Z:")
print(f"  BCD   : {bcd4}")
print(f"  Target: {target4}")
print(f"  结果  : {r}  {'✅ PASS' if r else '❌ FAIL'}")

print()
print("=" * 60)
print("【测试 5】[boot] 前缀 + 不位于引导分区 —— 不应匹配")
bcd5 = "ramdisk=[boot]\\isboot\\boot.wim,{ramdiskoptions}"
target5 = "D:\\isboot\\boot.wim"
r = match_wim_path_simulation(bcd5, target5, boot_drive_letter="Z:")
print(f"  BCD   : {bcd5}")
print(f"  Target: {target5}")
print(f"  结果  : {r}  {'✅ PASS' if not r else '❌ FAIL'}")

print()
print("=" * 60)
print("【测试 6】D 盘 WIM 同路径 —— 应匹配")
bcd6 = "ramdisk=[D:]\\Data\\temp\\k19045-20260111.wim,{ramdiskoptions}"
target6 = "D:\\Data\\temp\\k19045-20260111.wim"
r = match_wim_path_simulation(bcd6, target6, boot_drive_letter="Z:")
print(f"  BCD   : {bcd6}")
print(f"  Target: {target6}")
print(f"  结果  : {r}  {'✅ PASS' if r else '❌ FAIL'}")

print()
print("=" * 60)
print("【测试 7】完全不同文件 + 完全不同路径 —— 不应匹配")
bcd7 = "ramdisk=[D:]\\BOOT.wim,{ramdiskoptions}"
target7 = "D:\\Data\\temp\\k19045-20260111.wim"
r = match_wim_path_simulation(bcd7, target7, boot_drive_letter="Z:")
print(f"  BCD   : {bcd7}")
print(f"  Target: {target7}")
print(f"  结果  : {r}  {'✅ PASS' if not r else '❌ FAIL'}")