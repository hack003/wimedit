import re, subprocess

_BOOT_SECTION_TITLES = (
    'Windows Boot Loader', 'Windows Boot Manager', 'Firmware Boot Manager',
    'Windows 启动加载器', 'Windows 启动管理器', '固件启动管理器',
)
_ALL_BOOT_SECTION_TITLES = _BOOT_SECTION_TITLES + (
    'Resume from Hibernate', '从休眠状态恢复',
    'Windows Memory Tester', 'Windows 内存测试程序',
    'EMS Settings', 'EMS 设置',
    'Debugger Settings', '调试器设置',
    'RAM Defects', 'RAM 故障',
    'Global Settings', '全局设置',
    'Boot Loader Settings', '启动加载器设置',
    'Hypervisor Settings', '虚拟机监控程序设置',
    'Resume Loader Settings', '恢复加载器设置',
    'Device options', '设备选项',
    'Setup Ramdisk Options', '安装程序 Ramdisk 选项',
)
_BOOT_SECTION_TITLES_RE = re.compile('|'.join(re.escape(t) for t in _ALL_BOOT_SECTION_TITLES))
_PROP_IDENTIFIER = ('identifier', '标识符')
_PROP_DESCRIPTION = ('description', '描述')

r = subprocess.run(['bcdedit', '/enum', 'all'], capture_output=True, text=True, timeout=10)
out = r.stdout
lines = out.split('\n')

# 模拟 boot_manager._refresh_bcd_list 的解析逻辑
sections = []
i = 0
n = len(lines)

while i < n:
    line = lines[i].strip()
    if not line:
        i += 1
        continue
    next_line = lines[i + 1].strip() if i + 1 < n else ''
    is_section_title = (next_line and set(next_line) == {'-'}) or _BOOT_SECTION_TITLES_RE.search(line)
    if is_section_title:
        section = {'section_type': line, 'identifier': '', 'description': ''}
        print(f"\n=== 解析节: {line} ===")
        i += 1
        if i < n and set(lines[i].strip()) == {'-'}:
            i += 1
        while i < n:
            prop_line = lines[i].strip()
            if not prop_line:
                i += 1
                continue
            prop_next = lines[i + 1].strip() if i + 1 < n else ''
            if (prop_next and set(prop_next) == {'-'}) or _BOOT_SECTION_TITLES_RE.search(prop_line):
                break
            parts = prop_line.split(None, 1)
            if len(parts) >= 2:
                prop_name = parts[0].strip()
                prop_value = parts[1].strip()
                # 打印每个属性名，帮助诊断
                print(f"  prop_name='{prop_name}'  prop_value='{prop_value}'")
                if not section['identifier'] and prop_name in _PROP_IDENTIFIER:
                    section['identifier'] = prop_value
                    print(f"    -> 设置 identifier = {prop_value}")
                elif not section['description'] and prop_name in _PROP_DESCRIPTION:
                    section['description'] = prop_value
                    print(f"    -> 设置 description = {prop_value}")
            i += 1
        sections.append(section)
        print(f"  最终: identifier='{section['identifier']}'  description='{section['description']}'")
    else:
        i += 1

print(f"\n=== 最终显示列表 ===")
for sec in sections:
    sid = sec['identifier']
    desc = sec['description'] or sid
    print(f"  {desc}")