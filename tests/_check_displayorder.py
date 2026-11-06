import subprocess, re

_PROP_IDENTIFIER = ('identifier', '标识符')
_PROP_DESCRIPTION = ('description', '描述')

r = subprocess.run(['bcdedit', '/enum', 'all'], capture_output=True, text=True, timeout=10)
out = r.stdout
lines = out.split('\n')

sections = []
i = 0
n = len(lines)

# 先解析所有节
while i < n:
    line = lines[i].strip()
    if not line:
        i += 1
        continue
    next_line = lines[i + 1].strip() if i + 1 < n else ""
    if next_line and set(next_line) == {'-'}:
        section = {'section_type': line, 'identifier': '', 'description': '', 'props': {}}
        i += 1
        if i < n and set(lines[i].strip()) == {'-'}:
            i += 1
        while i < n:
            prop_line = lines[i].strip()
            if not prop_line:
                i += 1
                continue
            if i + 1 < n:
                nxt = lines[i + 1].strip()
                if nxt and set(nxt) == {'-'}:
                    break
            parts = prop_line.split(None, 1)
            if len(parts) >= 2:
                prop_name = parts[0].strip().lower()
                prop_value = parts[1].strip()
                if prop_name in ('identifier', '标识符'):
                    section['identifier'] = prop_value
                elif prop_name in ('description', '描述'):
                    section['description'] = prop_value
                # 收集所有属性
                section['props'][prop_name] = prop_value
            i += 1
        sections.append(section)
    else:
        i += 1

# 找 bootmgr 节
bootmgr = next((s for s in sections if s['identifier'] == '{bootmgr}'), None)
if bootmgr:
    print("=== {bootmgr} 节信息 ===")
    print(f"  section_type: {bootmgr['section_type']}")
    print(f"  description: {bootmgr['description']}")
    print(f"  displayorder: {bootmgr['props'].get('displayorder', 'N/A')}")
    print(f"  所有属性: {list(bootmgr['props'].keys())}")
else:
    print("找不到 {bootmgr} 节")

# 建立 GUID -> 节 的映射
sections_by_id = {s['identifier']: s for s in sections if s['identifier']}
# 也建立小写映射
sections_by_id_lower = {k.lower(): v for k, v in sections_by_id.items()}

print(f"\n=== 所有节的 identifier 映射 ===")
for s in sections:
    print(f"  {s['identifier']:50s} -> {s['section_type']} / {s['description']}")