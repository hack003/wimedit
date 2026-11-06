import subprocess, re

r = subprocess.run(['bcdedit', '/enum', 'all'], capture_output=True, text=True, timeout=10)
out = r.stdout
lines = out.split('\n')

_BRACE_RE = re.compile(r'^\{[^}]+\}$')

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
                brace_match = _BRACE_RE.match(prop_value)
                if brace_match:
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
                    brace_match = _BRACE_RE.match(prop_line)
                    if brace_match:
                        section["prop_lists"].setdefault(current_prop_name, []).append(prop_line)
                i += 1
        sections.append(section)
    else:
        i += 1

# 查找 bootmgr
sections_by_id = {s["identifier"]: s for s in sections if s["identifier"]}
sections_by_id_lower = {k.lower(): v for k, v in sections_by_id.items()}
bootmgr = sections_by_id.get("{bootmgr}") or sections_by_id_lower.get("{bootmgr}")

if bootmgr:
    print("=== {bootmgr} 的列表属性 ===")
    for k, v in bootmgr["prop_lists"].items():
        print(f"  {k}: {v}")

    # displayorder（严格匹配）
    menu_item_ids = []
    for key, vals in bootmgr["prop_lists"].items():
        if key == 'displayorder' or key == '显示顺序':
            menu_item_ids.extend(vals)

    if not menu_item_ids:
        for key in bootmgr["props"]:
            if 'default' in key:
                dv = bootmgr["props"][key]
                if _BRACE_RE.match(dv):
                    menu_item_ids.append(dv)

    print(f"\n=== 默认模式（仅 displayorder）的显示列表 ===")
    print(f"  displayorder 列表: {menu_item_ids}")

    alias_map = {}
    for prop_key, val in bootmgr["props"].items():
        if 'default' in prop_key and _BRACE_RE.match(val):
            alias_map["{default}"] = val
            alias_map["{default}".lower()] = val
    for prop_key, vals in bootmgr["prop_lists"].items():
        if 'default' in prop_key and vals and _BRACE_RE.match(vals[0]):
            alias_map["{default}"] = vals[0]
            alias_map["{default}".lower()] = vals[0]

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
                print(f"  {desc}")
                seen.add(gk)

    if not seen:
        print("  （displayorder 为空，尝试兜底：显示所有 Boot Loader 类型）")
        for s in sections:
            if not s["identifier"]: continue
            if s["identifier"].lower() in ("{current}", "{bootmgr}", "{fwbootmgr}"): continue
            s_type = s["section_type"]
            if "Boot Loader" in s_type or "启动加载器" in s_type:
                desc = s["description"] or s["identifier"]
                print(f"  {desc}")

    print("\n=== 高级模式（所有节，跳过 {current}） ===")
    for s in sections:
        if not s["identifier"]: continue
        if s["identifier"].lower() == "{current}": continue
        desc = s["description"] or s["identifier"]
        print(f"  {desc}")
else:
    print("找不到 {bootmgr} 节！")