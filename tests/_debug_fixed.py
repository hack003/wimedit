import re, subprocess

_PROP_IDENTIFIER = ('identifier', '标识符')
_PROP_DESCRIPTION = ('description', '描述')

r = subprocess.run(['bcdedit', '/enum', 'all'], capture_output=True, text=True, timeout=10)
out = r.stdout
lines = out.split('\n')

sections = []
i = 0
n = len(lines)

while i < n:
    line = lines[i].strip()
    if not line:
        i += 1
        continue

    # 节标题检测：只有下一行是 ---- 分隔线才是节标题
    next_line = lines[i + 1].strip() if i + 1 < n else ""
    is_section_title = next_line and set(next_line) == {'-'}

    if is_section_title:
        section = {'section_type': line, 'identifier': '', 'description': ''}
        print(f"\n=== {line} ===")
        i += 1  # 跳过标题
        if i < n and set(lines[i].strip()) == {'-'}:
            i += 1  # 跳过分隔线

        while i < n:
            prop_line = lines[i].strip()
            if not prop_line:
                i += 1
                continue

            # 检查当前行是否是下一个节的标题（下一行是 ----）
            if i + 1 < n:
                nxt = lines[i + 1].strip()
                if nxt and set(nxt) == {'-'}:
                    break

            parts = prop_line.split(None, 1)
            if len(parts) >= 2:
                prop_name = parts[0].strip()
                prop_value = parts[1].strip()
                if not section['identifier'] and prop_name in _PROP_IDENTIFIER:
                    section['identifier'] = prop_value
                    print(f"  identifier: {prop_value}")
                elif not section['description'] and prop_name in _PROP_DESCRIPTION:
                    section['description'] = prop_value
                    print(f"  description: {prop_value}")
            i += 1

        sections.append(section)
    else:
        i += 1

print(f"\n=== 显示列表 (共 {len(sections)} 项) ===")
for s in sections:
    desc = s['description'] or s['identifier'] or '(无描述)'
    print(f"  {desc}")