import sys
src_dir = r"d:\code\映像编辑辅助工具"
sys.path.insert(0, src_dir)
import os
# check all py files syntax
for fname in os.listdir(src_dir):
    if fname.endswith(".py"):
        fpath = os.path.join(src_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                compile(f.read(), fname, "exec")
            print("OK:", fname)
        except Exception as e:
            print("FAIL:", fname, "->", e)
# now import logger_utils to also verify runtime
import logger_utils
logger_utils.log("mount", "DEBUG", "test-1")
logger_utils.log("mount", "WARNING", "test-2")
logger_utils.log("unmount", "ERROR", "test-3")
logger_utils.set_log_level("WARNING")
print("filter global=WARNING:")
for l in logger_utils.get_filtered_lines():
    print(" ", l)
print("LEVEL_ORDER:", [(n, int(l), c) for n, l, c in logger_utils.LEVEL_ORDER])
print("global_level_name:", logger_utils.get_global_level_name())
print("runtime OK")