import os, tempfile, subprocess, time, shutil, sys

sys_temp = os.environ.get('TEMP')
bat = os.path.join(sys_temp, '_test_launch.bat')
mark = os.path.join(sys_temp, '_launch_test_output.txt')

with open(bat, 'w', encoding='utf-8') as f:
    f.write('@echo off\r\necho HELLO_FROM_BAT > "' + mark + '"\r\n')

def clean():
    if os.path.exists(mark):
        os.remove(mark)

# 方式 1：shell=True + cmd.exe /c ""path""
clean()
cmd = 'cmd.exe /c ""' + bat + '""'
print('[1] shell=True cmd =', cmd)
subprocess.Popen(cmd, shell=True)
time.sleep(2)
print('[1] output exists:', os.path.exists(mark))

# 方式 2：shell=True，直接 bat 路径
clean()
print('[2] shell=True bat')
subprocess.Popen(bat, shell=True)
time.sleep(2)
print('[2] output exists:', os.path.exists(mark))

# 方式 3：shell=False + list
clean()
print('[3] shell=False list')
subprocess.Popen(['cmd.exe', '/c', bat], shell=False)
time.sleep(2)
print('[3] output exists:', os.path.exists(mark))

# 方式 4：os.startfile
clean()
print('[4] os.startfile')
os.startfile(bat)
time.sleep(2)
print('[4] output exists:', os.path.exists(mark))

# 方式 5：用 DETACHED_PROCESS + CREATE_NO_WINDOW
clean()
print('[5] CREATE_NO_WINDOW DETACHED list')
subprocess.Popen(
    ['cmd.exe', '/c', bat],
    shell=False,
    creationflags=0x08000000 | 0x00000008
)
time.sleep(2)
print('[5] output exists:', os.path.exists(mark))

clean()
os.remove(bat)
print('DONE')