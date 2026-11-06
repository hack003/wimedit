import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logger_utils

# cleanup global state for tests
import importlib
importlib.reload(logger_utils)

logger_utils.log("mount", "DEBUG", "mount debug")
logger_utils.log("mount", "WARNING", "mount warning")
logger_utils.log("unmount", "ERROR", "unmount error")

print("--- global=ERROR (default) ---")
for l in logger_utils.get_filtered_lines():
    print(l)

print("--- set global=WARNING ---")
logger_utils.set_log_level("WARNING")
for l in logger_utils.get_filtered_lines():
    print(l)

print("--- set global=DEBUG ---")
logger_utils.set_log_level("DEBUG")
for l in logger_utils.get_filtered_lines():
    print(l)

print("--- set_module_level('mount','WARNING') ---")
logger_utils.set_module_level("mount", "WARNING")
print("effective mount:", logger_utils.get_effective_level_name("mount"))
print("effective unmount:", logger_utils.get_effective_level_name("unmount"))
print("global:", logger_utils.get_global_level_name())

print("--- known modules ---")
print(logger_utils.get_all_known_modules())