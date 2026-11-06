import sys
sys.path.insert(0, '.')
try:
    import boot_utils
    print('boot_utils: OK')
except Exception as e:
    print(f'boot_utils: {e}')
try:
    import boot_manager
    print('boot_manager: OK')
except Exception as e:
    print(f'boot_manager: {e}')
try:
    import boot_test
    print('boot_test: OK')
except Exception as e:
    print(f'boot_test: {e}')