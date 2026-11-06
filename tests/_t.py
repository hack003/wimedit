import sys
import os
# change cwd to script dir
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logger_utils

logger_utils.log("mount", "DEBUG", "mount-debug")
logger_utils.log("mount", "INFO", "mount-info")
logger_utils.log("mount", "WARNING", "mount-warn")
logger_utils.log("mount", "ERROR", "mount-err")

print("--- global=ERROR ---")
for l in logger_utils.get_filtered_lines():
    print(" ", l)

logger_utils.set_log_level("WARNING")
print("--- global=WARNING ---")
for l in logger_utils.get_filtered_lines():
    print(" ", l)

logger_utils.set_log_level("DEBUG")
print("--- global=DEBUG ---")
for l in logger_utils.get_filtered_lines():
    print(" ", l)

print("LEVEL_ORDER:", [(n, int(l), c) for n, l, c in logger_utils.LEVEL_ORDER])
print("global_level_name:", logger_utils.get_global_level_name())
print("syntax OK")