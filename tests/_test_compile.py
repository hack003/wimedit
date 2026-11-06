import py_compile, sys
ok = True
for f in [r"d:\code\映像编辑辅助工具\boot_utils.py",
          r"d:\code\映像编辑辅助工具\boot_add_menu.py",
          r"d:\code\映像编辑辅助工具\boot_manager.py"]:
    try:
        py_compile.compile(f, doraise=True)
        print("OK:", f)
    except Exception as e:
        print("FAIL:", f, e)
        ok = False
sys.exit(0 if ok else 1)