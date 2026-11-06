"""Quick DPI scaling smoke test - run to validate."""
import dpi_utils
print("scale_ratio =", dpi_utils.SCALE_RATIO)
print("px(100) =", dpi_utils.px(100))
print("dpi_geometry(540, 470) =", dpi_utils.dpi_geometry(540, 470))
print("font_scaled('Arial', 12) =", dpi_utils.font_scaled("Arial", 12))
print("font_scaled('Arial', 12, 'bold') =", dpi_utils.font_scaled("Arial", 12, "bold"))
print("scaled_tuple(5, 10) =", dpi_utils.scaled_tuple(5, 10))

# Test that the main entry can at least parse
print()
print("--- Testing imports from other modules ---")
from file_searcher import FileSearchDialog
print("file_searcher: OK")
from boot_test import BootTest
print("boot_test: OK")
from boot_manager import BootManager
print("boot_manager: OK")
from wim_editor import WimEditor
print("wim_editor: OK")
print()
print("DPI scaling integration: COMPLETE")