import os, tempfile, subprocess, time, shutil

sys_temp = os.environ.get('TEMP')
ts = str(int(time.time()))
tdir = os.path.join(sys_temp, '_wim_update_smoke_' + ts)
os.makedirs(tdir, exist_ok=True)

app_dir = os.path.join(sys_temp, '_wim_update_app_' + ts)
os.makedirs(app_dir, exist_ok=True)
old_exe = os.path.join(app_dir, '映像编辑辅助工具.exe')
with open(old_exe, 'wb') as f:
    f.write(b'OLD_EXE_MARKER_' + b'x' * 2048)

new_exe = os.path.join(tdir, '映像编辑辅助工具.new.exe')
with open(new_exe, 'wb') as f:
    f.write(b'NEW_EXE_MARKER_' + b'y' * 4096)

log_file = os.path.join(sys_temp, '_smoke_log_' + ts + '.txt')

# 自定义带调试输出的 bat
bat = os.path.join(sys_temp, '_wim_tool_updater_' + ts + '.bat')
content = (
    '@echo off\r\n'
    'chcp 65001 >nul\r\n'
    'echo START_UPDATE > "' + log_file + '"\r\n'
    'echo old_exe=' + old_exe + ' >> "' + log_file + '"\r\n'
    'echo new_exe=' + new_exe + ' >> "' + log_file + '"\r\n'
    'echo tdir=' + tdir + ' >> "' + log_file + '"\r\n'
    'timeout /t 2 /nobreak >nul\r\n'
    'if exist "' + old_exe + '" (del /f /q "' + old_exe + '" & echo DELETE_OK >> "' + log_file + '") else echo NO_OLD >> "' + log_file + '"\r\n'
    'move /y "' + new_exe + '" "' + old_exe + '" >> "' + log_file + '" 2>&1\r\n'
    'echo MOVE_DONE >> "' + log_file + '"\r\n'
    'timeout /t 1 /nobreak >nul\r\n'
    'if exist "' + tdir + '" (rd /s /q "' + tdir + '" & echo RMDIR_OK >> "' + log_file + '") else echo NO_TDIR >> "' + log_file + '"\r\n'
    'del /f /q "' + bat + '" 2>nul\r\n'
)
with open(bat, 'w', encoding='utf-8') as f:
    f.write(content)

print('bat:', bat)
print('tdir:', tdir)
print('old_exe exists:', os.path.exists(old_exe))

# 测试 launch_updater
import update
ok = update.launch_updater(bat)
print('launch_updater returned:', ok)

time.sleep(5)
print('--- After 5s ---')
print('old_exe exists:', os.path.exists(old_exe))
if os.path.exists(old_exe):
    with open(old_exe, 'rb') as f:
        head = f.read(24)
    print('old_exe head:', head)
print('tdir exists:', os.path.exists(tdir))
print('bat exists:', os.path.exists(bat))
if os.path.exists(log_file):
    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        print('--- LOG ---')
        print(f.read())

# cleanup
shutil.rmtree(app_dir, ignore_errors=True)
shutil.rmtree(tdir, ignore_errors=True)
for p in [bat, log_file]:
    try: os.remove(p)
    except: pass
print('CLEANUP DONE')