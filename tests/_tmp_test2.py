import sys
sys.path.insert(0, '.')
with open('test_output.txt', 'w', encoding='utf-8') as f:
    try:
        import boot_utils
        f.write('boot_utils: OK\n')
    except Exception as e:
        f.write(f'boot_utils: {e}\n')
    try:
        import boot_manager
        f.write('boot_manager: OK\n')
    except Exception as e:
        f.write(f'boot_manager: {e}\n')
    try:
        import boot_test
        f.write('boot_test: OK\n')
    except Exception as e:
        f.write(f'boot_test: {e}\n')