import subprocess, re

r = subprocess.run(['bcdedit', '/enum', 'all'], capture_output=True, text=True, timeout=10)
out = r.stdout
lines = out.split('\n')

_GUID_RE = re.compile(r'\{[0-9a-fA-F-]+\}')

# 解析所有节
sections = []
i = 0
n = len(lines)

while i < n:
    line = lines[i].strip()
    if not line:
        i += 1
        continue
    next_line = lines[i + 1].strip() if i + 1 < n else ""
    if next_line and set(next_line) == {'-'}:
        section = {"section_type": line, "identifier": "", "description": "", "props": {}, "prop_lists": {}}
        i += 1
        if i < n and set(lines[i].strip()) == {'-'}:
            i += 1
        current_prop_name = None
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
                    section["identifier"] = prop_value
                elif prop_name in ('description', '描述'):
                    section["description"] = prop_value
                guid_match = _GUID_RE.match(prop_value)
                if guid_match:
                    if prop_name not in section["prop_lists"]:
                        section["prop_lists"][prop_name] = []
                    section["prop_lists"][prop_name].append(prop_value)
                    current_prop_name = prop_name
                else:
                    section["props"][prop_name] = prop_value
                    current_prop_name = None
                i += 1
            else:
                if current_prop_name:
                    guid_match = _GUID_RE.match(prop_line)
                    if guid_match:
                        section["prop_lists"].setdefault(current_prop_name, []).append(prop_line)
                i += 1
        sections.append(section)
    else:
        i += 1

# 构建查找表
sections_by_id = {s["identifier"]: s for s in sections if s["identifier"]}
sections_by_id_lower = {k.lower(): v for k, v in sections_by_id.items()}

# 查找 bootmgr
bootmgr = sections_by_id.get("{bootmgr}") or sections_by_id_lower.get("{bootmgr}")

print("=== 所有节（调试）:")
for s in sections:
    sid = s["identifier"] or "(无id)"
    print(f"  {sid:50s} {s['section_type']} / {s['description']}")
    if s["prop_lists"]:
        for pk, pv in s["prop_lists"].items():
            print(f"    list: {pk} = {pv}")

if bootmgr:
    print(f"\n=== {bootmgr['identifier']}:")
    print(f"  section_type: {bootmgr['section_type']}")
    print(f"  description: {bootmgr['description']}")
    print(f"  props: {bootmgr['props']}")
    print(f"  prop_lists: {bootmgr['prop_lists']}")

    menu_item_ids = []
    if bootmgr:
        for key, vals in bootmgr["prop_lists"].items():
            if 'displayorder' in key:
                menu_item_ids.extend(vals)
        if not menu_item_ids:
            for key in bootmgr["props"]:
                if 'default' in key:
                    dv = bootmgr["props"][key]
                    if _GUID_RE.match(dv):
                        menu_item_ids.append(dv)
    print(f"\n=== displayorder 中的启动项 ID: {menu_item_ids}")

    # 建立别名映射
    alias_map = {}
    for prop_key, val in bootmgr["props"].items():
        if 'default' in prop_key and _GUID_RE.match(val):
            alias_map["{default}"] = val
            alias_map["{default}".lower()] = val
    for prop_key, vals in bootmgr["prop_lists"].items():
        if 'default' in prop_key and vals and _GUID_RE.match(vals[0]):
            alias_map["{default}"] = vals[0]
            alias_map["{default}".lower()] = vals[0]
    print(f"  别名映射: {alias_map}")

    print(f"\n=== 默认模式（只显示 displayorder 中的项）:")
    seen = set()
    for item_id in menu_item_ids:
        il = item_id.lower()
        resolved_id = alias_map.get(il, item_id)
        sec = sections_by_id.get(resolved_id) or sections_by_id_lower.get(resolved_id.lower())
        if not sec:
            sec = sections_by_id.get(item_id) or sections_by_id_lower.get(il)
        if sec and sec["identifier"]:
            gk = sec["identifier"].lower()
            if gk not in seen:
                desc = sec["description"] or sec["identifier"]
                print(f"  {desc} ({sec['identifier']})")
                seen.add(gk)

print(f"\n=== 高级模式（所有节，跳过 {{current}}）:")
for s in sections:
    if not s["identifier"]: continue
    if s["identifier"].lower() == "{current}": continue
    desc = s["description"] or s["identifier"]
    print(f"  {desc}")