import re, subprocess

r = subprocess.run(['bcdedit', '/enum', 'all'], capture_output=True, text=True, timeout=10)
out = r.stdout
lines = out.split('\n')

# 找所有节（以 "----" 分隔线标识节标题）
print("=== 完整 bcdedit /enum all 输出的节结构 ===")

section_titles = []
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped and set(stripped) == {'-'}:
        # 上一行是节标题
        if i > 0:
            title = lines[i-1].strip()
            section_titles.append((i, title))
            print(f"\n=== 节: {title} (在第 {i} 行) ===")
            # 打印这个节的 identifier 和 description
            for j in range(i+1, min(i+20, len(lines))):
                pline = lines[j].strip()
                if not pline:
                    continue
                if set(pline) == {'-'}:
                    break
                # 只打印 identifier/description
                parts = pline.split(None, 1)
                if len(parts) >= 2:
                    prop_name = parts[0].lower()
                    if 'identifier' in prop_name or 'description' in prop_name or prop_name in ('描述', '标识符'):
                        print(f"  {pline}")
                # 检查是否是下一个节标题（下一行是 ----）
                if j + 1 < len(lines):
                    next_line = lines[j+1].strip()
                    if next_line and set(next_line) == {'-'}:
                        break

print(f"\n\n共找到 {len(section_titles)} 个节")