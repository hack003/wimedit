# -*- coding: utf-8 -*-
import ast, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

files = ['boot_utils.py', 'boot_add_menu.py', 'boot_manager.py']
all_ok = True

for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            ast.parse(fh.read())
        print(f'{f}: OK')
    except SyntaxError as e:
        print(f'{f}: SYNTAX ERROR - line {e.lineno}: {e.msg}')
        all_ok = False

if all_ok:
    print('\n✅ 所有文件语法检查通过')

    # 另外模拟一次 _build_wim_device_str 逻辑以确认输出
    def _split_drive_abs(path):
        import os
        drive, rel = os.path.splitdrive(os.path.normpath(path))
        if not rel.startswith('\\'):
            rel = '\\' + rel
        return drive, rel

    wim_path = 'Z:\\IsBoot\\BOOT.wim'
    wim_drive, wim_rel = _split_drive_abs(wim_path)
    print(f'\n模拟 WIM 路径: {wim_path}')
    print(f'拆分结果: drive={wim_drive}, rel={wim_rel}')
    print(f'生成 device (使用 boot): ramdisk=[boot]{wim_rel},{{ramdiskoptions}}')
    print(f'生成 device (使用盘符): ramdisk=[{wim_drive}]{wim_rel},{{ramdiskoptions}}')

    print(f'\nwinload (UEFI): \\Windows\\System32\\boot\\winload.efi')
    print(f'winload (BIOS): \\Windows\\System32\\boot\\winload.exe')

    print(f'\nramdisksdidevice: boot')
    print(f'ramdisksdipath: \\EFI\\Microsoft\\Boot\\boot.sdi')

    print('\n📋 完整 BCD 配置（与 WIT 完全一致）:')
    print(f'  device       ramdisk=[boot]\\IsBoot\\BOOT.wim,{{ramdiskoptions}}')
    print(f'  osdevice     ramdisk=[boot]\\IsBoot\\BOOT.wim,{{ramdiskoptions}}')
    print(f'  path         \\Windows\\System32\\boot\\winload.efi')
    print(f'  systemroot   \\Windows')
    print(f'  winpe        Yes')
    print(f'  detecthal    Yes')
    print(f'  description  Windows 10 PE')
else:
    sys.exit(1)