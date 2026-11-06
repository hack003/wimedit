import subprocess

r = subprocess.run(['bcdedit', '/enum', 'all'], capture_output=True, text=True, timeout=10)
out = r.stdout
lines = out.split('\n')

# 打印行号和内容，只打印关键区域（包含 bootmgr 和下一个节之间的内容）
print("=== 原始输出（bootmgr 区域）===\n")
bootmgr_line = -1
for i, line in enumerate(lines):
    stripped = line.strip()
    if 'bootmgr' in stripped.lower() or '启动管理器' in stripped:
        bootmgr_line = i
        print(f"[{i:3d}] {repr(line)}")
        # 打印前后 15 行
        for j in range(max(0, i-2), min(len(lines), i+30)):
            s = lines[j].strip()
            marker = " <-- 仅'-'行" if s and set(s) == {'-'} else ""
            marker2 = " <-- 空行" if not s else ""
            print(f"[{j:3d}] {repr(lines[j])}{marker}{marker2}")
        print("\n...")
        break

# 也打印整个输出的前 60 行看看整体格式
print("\n=== 整个输出的前 60 行格式概览 ===")
for i in range(min(60, len(lines))):
    stripped = lines[i].strip()
    marker = ""
    if stripped and set(stripped) == {'-'}:
        marker = " <-- 分隔线（节标题标识）"
    elif not stripped:
        marker = " <-- 空行"
    print(f"[{i:3d}] {lines[i]}{marker}")