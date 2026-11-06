# -*- coding: utf-8 -*-
"""引导环境检测和操作工具模块

提供引导环境检测、EFI分区管理、离线系统查找、BCD操作等通用功能
供 boot_manager.py 和 boot_test.py 共同使用

ESP挂载策略：
- 全平台统一：mountvol /L 快速筛选 + mountvol 盘符 /S 直接挂载（高速、不扫盘）
- 全局缓存：_efi_mount_global + _efi_scanned，两个Tab只调用统一 ensure_efi_mounted()
- 系统限制：mountvol 挂载的盘符对资源管理器隔离，explorer 打不开属正常现象
- 解决方案：软件内置 IsBoot 目录文件列表+多选删除，用户无需进文件夹

注：diskpart 等方案均无法绕过 Win10/11 对 ESP 挂载盘符的权限隔离
     explorer "位置不可用" 是系统层面限制，不是挂载工具问题。
"""

import os
import sys
import re
import shutil
import string
import tempfile
import subprocess
from datetime import datetime

try:
    import winreg  # noqa: F401
except ImportError:
    winreg = None

try:
    import ctypes  # noqa: F401
except ImportError:
    ctypes = None


class BootEnvironmentDetector:
    """引导环境检测器"""

    _efi_mount_global = None   # 全局EFI分区挂载状态（如 "Z:\\"）
    _efi_scanned = False       # 是否已执行过一次ESP扫描（避免重复扫描）

    _BOOT_DEFAULTS = {
        'boot_mode': 'bios',
        'has_efi': False,
        'bcd_store_path': None,
        'boot_sdi_path': None
    }

    def __init__(self, log_callback=None, data_dir=None):
        self._log = log_callback or (lambda x: None)
        self._boot_env_cache = None
        self._bcd_cache = None
        self._efi_mount_cache = None
        # data_dir 参数保留，供上层传参；本模块不再依赖 data/boot 目录
        _ = data_dir

    @staticmethod
    def _get_sys_drive():
        """返回当前系统根目录所在的盘符，例如 'C:\\'"""
        return os.path.splitdrive(os.environ.get('SystemRoot', 'C:\\Windows'))[0] + '\\'

    @staticmethod
    def _get_windows_version():
        """获取当前Windows版本号，返回 (major, minor, is_pe)

        win7 = (6, 1)
        win8 = (6, 2) / (6, 3)
        win10 = (10, 0)
        win11 = (10, 0)  # 版本号同为10.0，通过build号进一步区分
        """
        is_pe = os.path.exists("X:\\")
        try:
            ver = sys.getwindowsversion()
            return (ver.major, ver.minor, is_pe)
        except Exception:
            return (6, 1, is_pe)  # 默认保守回退

    def _get_free_drive_letter(self):
        """统一使用 Z 盘作为 ESP 分区挂载点"""
        return "Z"

    def detect_boot_environment(self):
        """检测当前引导环境：UEFI、BIOS 或 PE"""
        if self._boot_env_cache is not None:
            return self._boot_env_cache

        result = dict(self._BOOT_DEFAULTS)
        result['target_drive'] = self._get_sys_drive()
        result['is_pe'] = False

        try:
            is_pe = os.path.exists("X:\\")
            result['is_pe'] = is_pe

            if is_pe:
                offline_drive = self.find_offline_system_drive()
                if offline_drive:
                    result['target_drive'] = offline_drive
                    has_efi = self.check_efi_partition(offline_drive)
                    result['has_efi'] = has_efi
                    result['boot_mode'] = 'uefi' if has_efi else 'bios'
                else:
                    result['boot_mode'] = 'pe'
            else:
                ok, out = self.run_get(["mountvol", "/L"], "检查EFI分区")
                if ok:
                    if '\\EFI\\' in out or 'EFI' in out.upper():
                        result['boot_mode'] = 'uefi'
                        result['has_efi'] = True
                    else:
                        result['boot_mode'] = 'bios'
                elif winreg is not None:
                    try:
                        with winreg.OpenKey(
                            winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control"
                        ) as key:
                            value, _ = winreg.QueryValueEx(key, "PEFirmwareType")
                        result['boot_mode'] = 'uefi' if value == 2 else 'bios'
                        result['has_efi'] = (value == 2)
                    except OSError:
                        result['boot_mode'] = 'bios'
                else:
                    result['boot_mode'] = 'bios'

            # 查找BCD和boot.sdi路径
            self._find_bcd_and_sdi_paths(result)

        except Exception as e:
            self._log(f"检测引导环境失败: {e}")
            result['boot_mode'] = 'bios'

        self._boot_env_cache = result
        return result

    def _find_bcd_and_sdi_paths(self, result):
        """查找BCD存储路径（boot.sdi的搜索和复制由ensure_ramdisk_options统一处理）"""
        boot_mode = result['boot_mode']
        target_drive = result['target_drive']

        if boot_mode == 'uefi':
            efi_mount = self.ensure_efi_mounted(result)
            if efi_mount:
                bcd_path = os.path.join(efi_mount, "EFI", "Microsoft", "Boot", "BCD")
                if os.path.exists(bcd_path):
                    result['bcd_store_path'] = bcd_path
                    self._log(f"BCD路径: {bcd_path}")
        else:
            bcd_path = os.path.join(target_drive, "Boot", "BCD")
            if os.path.exists(bcd_path):
                result['bcd_store_path'] = bcd_path
                self._log(f"BCD路径: {bcd_path}")

    def find_boot_sdi_source(self, base_dir=None, data_dir=None):
        """查找boot.sdi源文件（按可靠性优先级搜索，找到第一个有效文件即返回）"""

        def _is_valid_sdi(path):
            """文件有效性校验：存在 + 是文件 + 大小 > 50KB（boot.sdi 通常 1-3MB）"""
            try:
                return os.path.isfile(path) and os.path.getsize(path) > 50 * 1024
            except OSError:
                return False

        candidates = []

        sys_drive = self._get_sys_drive()
        candidates.append(os.path.join(sys_drive, "Windows", "System32", "boot.sdi"))

        if base_dir:
            candidates.append(os.path.join(base_dir, "Boot", "boot.sdi"))

        if data_dir:
            candidates.append(os.path.join(data_dir, "Boot", "boot.sdi"))
            candidates.append(os.path.join(data_dir, "boot.sdi"))

        if getattr(sys, 'frozen', False):
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass:
                candidates.append(os.path.join(meipass, "Boot", "boot.sdi"))

        for path in candidates:
            path = os.path.normpath(path)
            if _is_valid_sdi(path):
                self._log(f"找到 boot.sdi 源文件: {path}")
                return path

        self._log("未找到可用的 boot.sdi 源文件")
        return None

    def check_efi_partition(self, drive_letter):
        """检查指定盘符的系统是否有UEFI引导分区（快速检测，不做全盘扫描）"""
        try:
            letter = drive_letter[0].upper()

            # 方法1: mountvol /L 快速检测（若可用）
            ok, out = self.run_get(["mountvol", "/L"], "检查EFI分区")
            if ok and ('\\EFI\\' in out or 'EFI' in out.upper()):
                self._log("mountvol检测到EFI分区")
                return True

            # 方法2: 检查目标系统盘下是否有 EFI 目录
            efi_path = os.path.join(drive_letter, "EFI")
            if os.path.exists(efi_path):
                self._log(f"发现EFI目录: {efi_path}")
                return True

            # 方法3: 检查 Z:\EFI 是否存在（已挂载）
            if os.path.exists("Z:\\EFI"):
                self._log("发现已挂载的 ESP 分区（Z:\\）")
                return True

            return False

        except Exception as e:
            self._log(f"检查UEFI分区失败: {e}")
            return False

    def find_offline_system_drive(self):
        """在 PE 环境中查找真正的离线系统盘（排除X盘等虚拟盘）"""
        try:
            self._log("查找离线系统盘（排除PE虚拟盘）...")

            current_drive = self._get_sys_drive()
            available_drives = []
            for letter in string.ascii_uppercase:
                if letter == 'X':
                    continue
                drive = f"{letter}:\\"
                if drive == current_drive:
                    continue
                if os.path.exists(drive):
                    available_drives.append(drive)

            # 检查每个盘符，判断是否为真正的Windows系统
            required_paths = ("Windows", "Windows/System32", "Windows/System32/config")
            for drive in available_drives:
                if not all(os.path.exists(os.path.join(drive, p)) for p in required_paths):
                    continue

                # 方法1: 读取注册表判断系统类型
                product_name = self.read_offline_registry(drive, "ProductName")
                if product_name:
                    self._log(f"{drive} - {product_name}")
                    if "PE" not in product_name.upper():
                        self._log(f"找到离线系统盘: {drive} ({product_name})")
                        return drive
                    self._log(f"{drive} 是PE系统，跳过")
                    continue

                # 方法2: 检查是否有 Program Files 和 Users 目录
                program_files = os.path.join(drive, "Program Files")
                users_dir = os.path.join(drive, "Users")

                if os.path.exists(program_files) and os.path.exists(users_dir):
                    self._log(f"找到离线系统盘: {drive} (有Program Files和Users目录)")
                    return drive

            self._log("未找到离线系统盘")
            return None

        except Exception as e:
            self._log(f"查找离线系统盘失败: {e}")
            return None

    def read_offline_registry(self, drive, value_name):
        """读取离线系统的注册表值（直接加载原始hive，无需复制）"""
        if winreg is None:
            self._log("当前系统不支持winreg，无法读取离线注册表")
            return None

        software_hive = os.path.join(drive, "Windows", "System32", "config", "SOFTWARE")
        if not os.path.exists(software_hive):
            return None

        # 直接加载原始hive文件，无需复制
        ok, _ = self.run_get(["reg", "load", "HKLM\\TempHive", software_hive], "加载离线注册表")
        if not ok:
            self._log("加载离线注册表失败")
            return None

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"TempHive\Microsoft\Windows NT\CurrentVersion"
            ) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                return value
        except OSError as e:
            self._log(f"读取注册表值失败: {e}")
            return None
        finally:
            self.run_get(["reg", "unload", "HKLM\\TempHive"], "卸载离线注册表")

    # ==============================================================
    # 核心：ESP分区挂载 / 卸载
    # ==============================================================

    def mount_efi_partition(self):
        """挂载 ESP 分区到 Z 盘（固定挂载点，纯 mountvol，无磁盘扫描，快速）"""
        # 全局缓存：只扫一次
        if BootEnvironmentDetector._efi_mount_global is not None:
            self._log(f"EFI分区已全局挂载: {BootEnvironmentDetector._efi_mount_global}")
            return BootEnvironmentDetector._efi_mount_global

        # 检查 Z:\EFI 是否已存在（之前已挂载）
        if os.path.exists("Z:\\EFI"):
            self._log("ESP分区已挂载到Z:盘")
            BootEnvironmentDetector._efi_mount_global = "Z:\\"
            return "Z:\\"

        # 已扫过一次且失败：直接返回 None，不再扫
        if BootEnvironmentDetector._efi_scanned:
            return None

        mount_point = "Z:\\"
        self._log("尝试挂载ESP分区到Z:盘（mountvol /S，高速模式）...")
        BootEnvironmentDetector._efi_scanned = True

        # 方式1: mountvol 盘符 /S（Win8+推荐）
        ok, _ = self.run_get(
            ["mountvol", mount_point, "/S"],
            "挂载ESP分区到Z:盘（mountvol /S）"
        )
        if ok and os.path.exists("Z:\\EFI"):
            self._log("✔ ESP分区已挂载: Z:\\")
            BootEnvironmentDetector._efi_mount_global = mount_point
            return mount_point

        # 方式2: mountvol /L 快速筛选 GUID 卷路径
        self._log("mountvol /S 未成功，尝试通过 GUID 卷路径挂载")
        ok, out = self.run_get(["mountvol", "/L"], "查找EFI分区")
        if ok:
            lines = [line.strip() for line in out.strip().split('\n') if line.strip()]
            for i, line in enumerate(lines):
                if ('\\EFI\\' in line or 'EFI' in line.upper()) and i > 0:
                    efi_volume = lines[i - 1]
                    if efi_volume.startswith('\\\\') or efi_volume.startswith('\\?'):
                        ok2, _ = self.run_get(
                            ["mountvol", mount_point, efi_volume],
                            "挂载EFI分区到Z:盘"
                        )
                        if ok2 and os.path.exists("Z:\\EFI"):
                            self._log("✔ ESP分区已挂载: Z:\\")
                            BootEnvironmentDetector._efi_mount_global = mount_point
                            return mount_point

        # 方式3: BIOS 环境或 mountvol 不支持的场景
        #    直接用 target_drive 作为 ESP 路径（C:\EFI 或 C:\boot）
        sys_drive = self._get_sys_drive()
        if os.path.isdir(os.path.join(sys_drive, "EFI")) or os.path.isdir(os.path.join(sys_drive, "Boot")):
            self._log("未挂载独立 ESP 分区，使用系统盘引导路径: " + sys_drive)
            BootEnvironmentDetector._efi_mount_global = sys_drive
            return sys_drive

        self._log("未找到或无法挂载 ESP 分区")
        return None

    # ==============================================================

    def unmount_efi_partition(self):
        """卸载已挂载的ESP分区（固定 Z 盘）"""
        mount_pt = BootEnvironmentDetector._efi_mount_global
        if mount_pt is None and not os.path.exists("Z:\\EFI"):
            self._log("ESP分区未挂载，无需卸载")
            return True

        self._log("尝试卸载ESP分区（Z:）...")

        # 首选: mountvol Z: /D
        ok, _ = self.run_get(["mountvol", "Z:", "/D"], "卸载ESP分区（Z:）")
        if ok or not os.path.exists("Z:\\EFI"):
            BootEnvironmentDetector._efi_mount_global = None
            # 注意：_efi_scanned 保留 True，避免重复扫描
            self._log("✔ ESP分区已卸载")
            return True

        # 回退: 大小写兼容 /d
        ok, _ = self.run_get(["mountvol", "Z:", "/d"], "尝试mountvol卸载ESP（Z:）")
        BootEnvironmentDetector._efi_mount_global = None
        self._log("已尝试卸载ESP分区，当前状态: " + ("Z:不存在" if not os.path.exists("Z:\\EFI") else "Z:仍可访问"))
        return True

    def ensure_efi_mounted(self, boot_env=None):
        """确保EFI分区已挂载并返回挂载路径（固定 Z 盘）

        统一入口：两个 Tab 均只调用此方法
        """
        # 1. 全局缓存命中
        if BootEnvironmentDetector._efi_mount_global is not None:
            self._log(f"EFI分区已全局挂载: {BootEnvironmentDetector._efi_mount_global}")
            return BootEnvironmentDetector._efi_mount_global

        # 2. 已扫描过无ESP
        if BootEnvironmentDetector._efi_scanned:
            self._log("已扫描过无ESP分区，跳过重复扫描")
            return None

        # 3. 实例缓存
        if self._efi_mount_cache is not None:
            return self._efi_mount_cache

        self._log("UEFI环境，检查EFI分区挂载状态...")

        # 4. 快速探测：Z:\EFI 已存在
        if os.path.exists("Z:\\EFI"):
            self._efi_mount_cache = "Z:\\"
            BootEnvironmentDetector._efi_mount_global = "Z:\\"
            BootEnvironmentDetector._efi_scanned = True
            self._log("发现已挂载的 ESP 分区: Z:\\")
            return "Z:\\"

        # 5. 检查系统根是否有 EFI 目录（某些配置下）
        sys_drive = self._get_sys_drive()
        for path in (sys_drive, "C:\\"):
            try:
                if not os.path.exists(path):
                    continue
                efi_path = os.path.join(path, "EFI", "Microsoft", "Boot", "BCD")
                if os.path.exists(efi_path):
                    self._efi_mount_cache = path
                    BootEnvironmentDetector._efi_mount_global = path
                    BootEnvironmentDetector._efi_scanned = True
                    self._log(f"发现已挂载的EFI分区: {path}")
                    return path
            except OSError:
                continue

        # 6. 执行真正的挂载流程
        self._log("ESP分区未挂载，开始分配盘符 Z...")
        mounted_path = self.mount_efi_partition()
        # 标记：无论成功与否，已扫描过
        BootEnvironmentDetector._efi_scanned = True
        if mounted_path:
            self._efi_mount_cache = mounted_path
            return mounted_path

        self._log("警告: 无法挂载EFI分区")
        return None

    def get_bcd_args(self, force_mount=False, boot_env=None):
        """获取BCD参数，根据引导环境自动返回正确的/store参数"""
        if self._bcd_cache is not None and not force_mount:
            return self._bcd_cache

        if boot_env is None:
            boot_env = self.detect_boot_environment()

        is_pe = boot_env['is_pe']
        boot_mode = boot_env['boot_mode']
        target_drive = boot_env['target_drive']

        self._log(f"当前环境: {'PE' if is_pe else '非PE'}-{boot_mode.upper()}, 目标盘: {target_drive}")

        if boot_mode == 'uefi':
            # UEFI模式：BCD在ESP分区\EFI\Microsoft\Boot\BCD
            efi_mount = self.ensure_efi_mounted(boot_env)
            if efi_mount:
                bcd_path = os.path.join(efi_mount, "EFI", "Microsoft", "Boot", "BCD")
                if os.path.exists(bcd_path):
                    self._bcd_cache = ["/store", bcd_path]
                    self._log(f"UEFI环境，使用ESP分区BCD: {bcd_path}")
                    return self._bcd_cache
                else:
                    self._log(f"警告: ESP分区中未找到BCD文件: {bcd_path}")
                    self._log("尝试使用默认BCD（可能需要修复引导）")
            else:
                self._log("警告: 无法挂载EFI分区，使用默认BCD")
        else:
            # BIOS模式：BCD在活动分区\Boot\BCD
            bcd_path = os.path.join(target_drive, "Boot", "BCD")

            if os.path.exists(bcd_path):
                self._bcd_cache = ["/store", bcd_path]
                self._log(f"BIOS环境，使用活动分区BCD: {bcd_path}")
                return self._bcd_cache
            else:
                self._log(f"警告: 未找到BCD文件: {bcd_path}")

        self._log("使用默认BCD（系统当前加载的BCD存储）")
        self._bcd_cache = []
        return self._bcd_cache

    def is_admin(self):
        """检查是否以管理员身份运行"""
        if ctypes is None:
            return False
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except OSError:
            return False

    def decode(self, data):
        """解码字节数据为字符串"""
        if isinstance(data, bytes):
            for enc in ('gbk', 'utf-8', 'gb2312', 'cp936', 'latin-1'):
                try:
                    return data.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return data.decode('gbk', errors='replace')
        return str(data)

    def _run_cmd(self, cmd, desc="", log_output=False):
        """通用命令执行逻辑，返回(成功状态, 输出文本)"""
        try:
            if desc:
                self._log(desc)
            p = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            raw = p.communicate()[0]
            out = self.decode(raw)
            if log_output:
                for line in out.split("\n"):
                    line = line.strip()
                    if line:
                        self._log(line)
            return p.returncode == 0, out
        except Exception as e:
            self._log(f"错误: {e}")
            return False, ""

    def run(self, cmd, desc=""):
        """运行命令并记录输出"""
        ok, _ = self._run_cmd(cmd, desc, log_output=True)
        return ok

    def run_get(self, cmd, desc="", log_output=False):
        """运行命令并返回(成功状态, 输出)"""
        return self._run_cmd(cmd, desc, log_output=log_output)

    def ensure_ramdisk_options(self, base_dir=None, data_dir=None):
        """确保 {ramdiskoptions} 存在并正确配置 boot.sdi

        处理流程（6步）：
        1. 定位引导分区（UEFI=ESP，BIOS=活动分区）
        2. 检查BCD中是否已有完整的 ramdiskoptions 配置
        3. 扫描引导分区内是否已有可用 boot.sdi
        4. 按优先级查找 boot.sdi 源文件
        5. 复制到引导分区标准路径
        6. 配置 BCD {ramdiskoptions}（固定 ramdisksdidevice=boot, ramdisksdipath=\\Boot\\boot.sdi）

        Returns:
            bool: 成功返回 True，失败返回 False（调用方应终止后续操作）
        """

        def _is_valid_sdi(path):
            try:
                return os.path.isfile(path) and os.path.getsize(path) > 50 * 1024
            except OSError:
                return False

        self._log("=== 开始配置 boot.sdi ===")

        boot_env = self.detect_boot_environment()
        boot_mode = boot_env.get('boot_mode', 'bios')
        bcd_args = self.get_bcd_args()

        boot_partition = None
        if boot_mode == 'uefi':
            boot_partition = self.ensure_efi_mounted(boot_env)
        else:
            boot_partition = boot_env.get('target_drive') or self._get_sys_drive()

        if not boot_partition:
            self._log("失败: 无法定位引导分区")
            return False

        self._log(f"引导模式: {boot_mode}, 引导分区: {boot_partition}")

        standard_sdi = os.path.normpath(os.path.join(boot_partition, "Boot", "boot.sdi"))

        if boot_mode == 'uefi':
            alt_sdi = os.path.normpath(os.path.join(boot_partition, "EFI", "Microsoft", "Boot", "boot.sdi"))
        else:
            alt_sdi = None

        self._log("检查BCD中现有 {ramdiskoptions} 配置...")
        ok, bcd_output = self.run_get(["bcdedit"] + bcd_args + ["/enum", "{ramdiskoptions}"], "读取ramdiskoptions")

        # 检查输出是否真的是 ramdiskoptions 条目（而不是其他条目）
        is_ramdisk_entry = False
        if ok and bcd_output:
            # 检查输出中是否包含 ramdiskoptions 标识符或 ramdisksdidevice 属性
            is_ramdisk_entry = ("ramdiskoptions" in bcd_output.lower() or 
                               "ramdisksdidevice" in bcd_output or
                               "ramdisksdipath" in bcd_output)

        if ok and bcd_output and is_ramdisk_entry:
            has_device = "ramdisksdidevice" in bcd_output
            has_path = "ramdisksdipath" in bcd_output
            if has_device and has_path:
                if _is_valid_sdi(standard_sdi):
                    self._log("{ramdiskoptions} 已有完整配置，且 {standard_sdi} 有效，跳过复制")
                    return True
                if alt_sdi and _is_valid_sdi(alt_sdi):
                    self._log("BCD配置存在，但 boot.sdi 位于非标准路径，需要重新配置")
                else:
                    self._log("BCD配置存在，但指向的 boot.sdi 文件不存在或损坏，需要重新配置")
            else:
                self._log("{ramdiskoptions} 存在但参数不完整，需要重新配置")
        else:
            self._log("{ramdiskoptions} 不存在或读取失败，需要创建")

        if _is_valid_sdi(standard_sdi):
            self._log(f"引导分区内已有 boot.sdi: {standard_sdi}，跳过复制")
            need_copy = False
        elif alt_sdi and _is_valid_sdi(alt_sdi):
            self._log(f"找到旧路径 boot.sdi: {alt_sdi}，需复制到标准路径以统一配置")
            need_copy = True
        else:
            self._log("引导分区内无可用 boot.sdi，需要复制")
            need_copy = True

        if need_copy:
            self._log("按优先级查找 boot.sdi 源文件...")
            boot_sdi_src = self.find_boot_sdi_source(base_dir, data_dir)
            if not boot_sdi_src:
                self._log("错误: 找不到 boot.sdi 源文件，请确认系统完整性或程序目录是否包含 Boot/boot.sdi")
                return False

            self._log(f"源文件: {boot_sdi_src}")

            target_dir = os.path.dirname(standard_sdi)
            try:
                if not os.path.isdir(target_dir):
                    os.makedirs(target_dir, exist_ok=True)
                    self._log(f"已创建目录: {target_dir}")
            except OSError as e:
                self._log(f"错误: 无法创建目录 {target_dir}: {e}")
                return False

            try:
                src_size = os.path.getsize(boot_sdi_src)
                shutil.copy2(boot_sdi_src, standard_sdi)
                dst_size = os.path.getsize(standard_sdi)
                if abs(src_size - dst_size) > 1024:
                    try:
                        os.remove(standard_sdi)
                    except OSError:
                        pass
                    self._log(f"错误: 复制后文件大小不符（源={src_size}, 目标={dst_size}），已删除残缺文件")
                    return False
                self._log(f"已复制 boot.sdi 到: {standard_sdi}（大小校验通过: {src_size} 字节）")
            except OSError as e:
                self._log(f"错误: 复制 boot.sdi 失败: {e}")
                return False

        if not _is_valid_sdi(standard_sdi):
            self._log(f"错误: 目标 boot.sdi 仍然不可用: {standard_sdi}")
            return False

        self._log("配置BCD {ramdiskoptions}...")

        # 检查 {ramdiskoptions} 是否真的存在（不是其他条目的输出）
        ok, check_out = self.run_get(["bcdedit"] + bcd_args + ["/enum", "{ramdiskoptions}"], "检查ramdiskoptions")
        is_real_entry = ok and check_out and ("ramdiskoptions" in check_out.lower() or "ramdisksdidevice" in check_out)

        if not is_real_entry:
            self._log("{ramdiskoptions} 不存在，创建中...")
            ok_create, create_out = self.run_get(
                ["bcdedit"] + bcd_args + ["/create", "{ramdiskoptions}"],
                "创建ramdiskoptions"
            )
            if not ok_create:
                self._log(f"创建失败: {create_out}")
                self._log("尝试重建BCD存储...")
                return self._rebuild_bcd_with_ramdiskoptions(bcd_args, boot_mode, boot_partition)

        if not self.run(
            ["bcdedit"] + bcd_args + ["/set", "{ramdiskoptions}", "ramdisksdidevice", "boot"],
            "设置ramdisksdidevice=boot"
        ):
            self._log("错误: 设置 ramdisksdidevice 失败")
            return False

        if not self.run(
            ["bcdedit"] + bcd_args + ["/set", "{ramdiskoptions}", "ramdisksdipath", "\\Boot\\boot.sdi"],
            "设置ramdisksdipath=\\Boot\\boot.sdi"
        ):
            self._log("错误: 设置 ramdisksdipath 失败")
            return False

        self._log("=== boot.sdi 配置完成 ===")
        return True

    def _rebuild_bcd_with_ramdiskoptions(self, bcd_args, boot_mode, boot_partition):
        """重建BCD存储，包含完整的 {ramdiskoptions} 配置"""
        bcd_store = None
        if len(bcd_args) >= 2 and bcd_args[0] == "/store":
            bcd_store = bcd_args[1]

        if not bcd_store:
            self._log("错误: 无法确定BCD存储路径")
            return False

        # 备份当前 BCD
        if os.path.exists(bcd_store):
            bak = bcd_store + ".bak_rebuild"
            try:
                shutil.copy2(bcd_store, bak)
                self._log(f"已备份BCD: {bak}")
            except OSError:
                pass

        # 删除旧 BCD
        try:
            if os.path.exists(bcd_store):
                os.remove(bcd_store)
                self._log("已删除损坏的BCD")
        except OSError as e:
            self._log(f"警告: 无法删除旧BCD: {e}")

        # 用 createstore 创建新的空 BCD
        ok_new, _ = self.run_get(
            ["bcdedit", "/createstore", bcd_store],
            "创建新BCD存储"
        )
        if not ok_new:
            self._log("错误: 创建新BCD存储失败")
            return False

        # 添加 {bootmgr}
        ok_bootmgr, _ = self.run_get(
            ["bcdedit", "/store", bcd_store, "/create", "{bootmgr}", "/d", "Windows Boot Manager"],
            "创建bootmgr"
        )
        if not ok_bootmgr:
            self._log("错误: 创建 bootmgr 失败")
            return False

        # 添加 {memdiag}
        self.run_get(
            ["bcdedit", "/store", bcd_store, "/create", "{memdiag}", "/d", "Windows Memory Diagnostic", "/application", "memdiag"],
            "创建memdiag"
        )

        # 添加 {default} OS loader
        ok_default, out_default = self.run_get(
            ["bcdedit", "/store", bcd_store, "/create", "/d", "Windows", "/application", "osloader"],
            "创建default osloader"
        )
        if not ok_default or not out_default:
            self._log("错误: 创建 default osloader 失败")
            return False

        import re as _re
        m = _re.search(r'\{[^\}]+\}', out_default)
        default_guid = m.group(0) if m else "{default}"

        # 设置 {default} 属性
        sys_drive = self._get_sys_drive()
        drive_letter = sys_drive.rstrip('\\') if sys_drive else "C:"
        winload = "\\Windows\\System32\\boot\\winload.exe" if boot_mode == 'bios' else "\\Windows\\System32\\boot\\winload.efi"
        for args in [
            ["/set", default_guid, "device", f"partition={drive_letter}"],
            ["/set", default_guid, "path", winload],
            ["/set", default_guid, "osdevice", f"partition={drive_letter}"],
            ["/set", default_guid, "systemroot", "\\Windows"],
            ["/set", default_guid, "locale", "zh-CN"],
            ["/set", default_guid, "inherit", "{bootloadersettings}"],
            ["/set", default_guid, "recoveryenabled", "Yes"],
        ]:
            self.run(["bcdedit", "/store", bcd_store] + args, "")

        # 设置 {bootmgr} 属性
        bp = boot_partition.rstrip('\\') if boot_partition else "C:"
        for args in [
            ["/set", "{bootmgr}", "device", f"partition={bp}"],
            ["/set", "{bootmgr}", "path", "\\boot\\bootmgr" if boot_mode == 'bios' else "\\EFI\\Microsoft\\Boot\\bootmgfw.efi"],
            ["/set", "{bootmgr}", "locale", "zh-CN"],
            ["/set", "{bootmgr}", "inherit", "{globalsettings}"],
            ["/set", "{bootmgr}", "default", default_guid],
            ["/set", "{bootmgr}", "displayorder", default_guid, "{memdiag}"],
            ["/set", "{bootmgr}", "timeout", "5"],
        ]:
            self.run(["bcdedit", "/store", bcd_store] + args, "")

        # 设置 {memdiag} 属性
        for args in [
            ["/set", "{memdiag}", "device", f"partition={bp}"],
            ["/set", "{memdiag}", "path", "\\Boot\\memtest.exe"],
            ["/set", "{memdiag}", "locale", "zh-CN"],
            ["/set", "{memdiag}", "inherit", "{globalsettings}"],
        ]:
            self.run(["bcdedit", "/store", bcd_store] + args, "")

        # 创建 {ramdiskoptions}
        ok_rd, _ = self.run_get(
            ["bcdedit", "/store", bcd_store, "/create", "{ramdiskoptions}"],
            "创建ramdiskoptions"
        )
        if not ok_rd:
            self._log("错误: 创建 {ramdiskoptions} 失败")
            return False

        # 设置 {ramdiskoptions} 属性
        for prop, value, desc in [
            ("ramdisksdidevice", "boot", "设置ramdisksdidevice=boot"),
            ("ramdisksdipath", "\\Boot\\boot.sdi", "设置ramdisksdipath"),
        ]:
            if not self.run(["bcdedit", "/store", bcd_store, "/set", "{ramdiskoptions}", prop, value], desc):
                self._log(f"错误: {desc} 失败")
                return False

        # 清除缓存
        self.clear_caches()
        self._log("BCD重建完成，包含 {ramdiskoptions}")
        return True

    def clear_caches(self):
        """清除所有缓存（不清除全局EFI挂载状态）"""
        self._boot_env_cache = None
        self._bcd_cache = None
        self._efi_mount_cache = None

    @staticmethod
    def unmount_efi_global():
        """程序退出时统一卸载EFI分区"""
        if BootEnvironmentDetector._efi_mount_global is not None:
            detector = BootEnvironmentDetector(log_callback=lambda msg: print(msg))
            detector.unmount_efi_partition()

    def refresh_boot_environment(self, force_refresh=False):
        """刷新引导环境信息"""
        if force_refresh:
            self.clear_caches()
        env_info = self.detect_boot_environment()
        self._log(f"当前环境: {'PE' if env_info['is_pe'] else '原生Windows'} - {env_info['boot_mode'].upper()}")
        if env_info['has_efi']:
            self._log("UEFI模式：BCD位于ESP分区\\EFI\\Microsoft\\Boot")
        else:
            self._log("BIOS模式：BCD位于活动分区\\Boot\\BCD")
        return env_info

    # ==============================================================
    # IsBoot 目录：文件列表 / 删除接口（解决 mountvol 挂载后 explorer 无法访问的问题）
    # ==============================================================

    def list_isboot_files(self, target_drive=None, extensions=None):
        """列出 IsBoot 目录下的文件（用于在程序中直接浏览、删除 WIM 镜像）

        target_drive: 可选，目标盘符（如 "C:" / "D:" / "Z:"）。若为 None 则自动选择：
                      - UEFI: 优先 ESP 分区(Z:)下的 IsBoot
                      - BIOS / 未挂载: 优先 C:\\IsBoot
        extensions: 可选，文件扩展名过滤列表，如 ['.wim', '.iso', '.sdi']。
                    传 None 则默认 ['.wim', '.iso']

        返回: list of dict，每项: {"name": str, "path": str, "size": int,
                                   "size_mb": float, "mtime": datetime|None}
              失败返回空列表
        """
        if extensions is None:
            extensions = ['.wim', '.iso']
        ext_lower = [e.lower() for e in extensions]

        # 1) 自动选择目标盘符
        if not target_drive:
            boot_env = self.detect_boot_environment()
            if boot_env.get('has_efi') or boot_env.get('boot_mode') == 'uefi':
                # UEFI：先尝试 ESP 分区(Z:) 下的 IsBoot
                efi = self.ensure_efi_mounted(boot_env)
                if efi and os.path.exists(os.path.join(efi, "IsBoot")):
                    target_drive = efi.rstrip("\\").rstrip(":") + ":"
            if not target_drive:
                target_drive = self._get_sys_drive().rstrip("\\").rstrip(":") + ":"

        # 2) 构造目标目录
        isboot_path = os.path.join(target_drive.rstrip("\\") + "\\", "IsBoot")
        result = []

        try:
            if not os.path.exists(isboot_path):
                self._log(f"IsBoot 目录不存在: {isboot_path}")
                return result

            self._log(f"扫描 IsBoot 目录: {isboot_path}")
            for name in os.listdir(isboot_path):
                full = os.path.join(isboot_path, name)
                try:
                    if not os.path.isfile(full):
                        continue
                    lower = name.lower()
                    if not any(lower.endswith(ext) for ext in ext_lower):
                        continue
                    st = os.stat(full)
                    size = st.st_size
                    try:
                        mtime = datetime.fromtimestamp(st.st_mtime)
                    except Exception:
                        mtime = None
                    result.append({
                        "name": name,
                        "path": full,
                        "size": size,
                        "size_mb": round(size / (1024 * 1024), 2),
                        "mtime": mtime,
                    })
                except OSError:
                    continue
            self._log(f"扫描完成，共 {len(result)} 个文件")
            return result
        except Exception as e:
            self._log(f"扫描 IsBoot 目录失败: {e}")
            return result

    def delete_isboot_file(self, file_path):
        """从 IsBoot 目录删除指定文件（先尝试普通 os.remove，失败再用 cmd del /F）

        返回: (bool, str)  (成功?，信息)
        """
        if not file_path or not os.path.exists(file_path):
            return False, f"文件不存在: {file_path}"

        # 简单的安全校验：必须在某个 IsBoot 目录下
        parent_lower = os.path.normpath(os.path.dirname(file_path)).lower()
        if "isboot" not in parent_lower:
            return False, f"安全拦截: {file_path} 不在 IsBoot 目录下"

        try:
            self._log(f"正在删除: {file_path}")
            os.remove(file_path)
            if not os.path.exists(file_path):
                return True, f"已删除: {os.path.basename(file_path)}"
        except PermissionError as e:
            self._log(f"os.remove 失败，尝试 cmd del /F: {e}")
        except Exception as e:
            self._log(f"删除文件失败: {e}")

        # 回退: cmd del /F /Q
        try:
            cmd = f'del /F /Q "{file_path}"'
            p = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            _out, _err = p.communicate()
            if not os.path.exists(file_path):
                return True, f"已删除(cmd): {os.path.basename(file_path)}"
            return False, f"cmd del 返回码 {p.returncode}，文件仍存在"
        except Exception as e2:
            return False, f"cmd del 也失败: {e2}"

    # ==============================================================
    # 复制 WIM 到指定目录（共享逻辑）
    # ==============================================================

    @staticmethod
    def copy_wim_to_dir(wim_path, dest_dir, log_fn=None):
        """复制 WIM 到目标目录（创建目录、删旧文件、检查空间、复制）

        流程：
        1. 创建目标目录（如不存在）
        2. 删除同名旧文件（释放空间，大小写不敏感）
        3. 检查磁盘空间（需 >= WIM 大小的 1.1 倍）
        4. 复制文件（shutil.copy2 失败则回退 cmd copy /Y）

        Args:
            wim_path: 源 WIM 文件路径
            dest_dir: 目标目录路径
            log_fn: 日志回调函数 log_fn(msg)

        Returns:
            (success: bool, result: str)
                success=True  -> result 为复制后的目标文件路径
                success=False -> result 为错误信息
        """
        def _log(msg):
            if log_fn:
                log_fn(msg)

        wim_path = os.path.normpath(wim_path)
        dest_dir = os.path.normpath(dest_dir)

        try:
            # 1. 创建目标目录
            if not os.path.exists(dest_dir):
                _log(f"创建目录: {dest_dir}")
                os.makedirs(dest_dir, exist_ok=True)

            dest_path = os.path.join(dest_dir, os.path.basename(wim_path))

            # 2. 删除同名旧文件（大小写不敏感，释放空间）
            try:
                dir_contents = os.listdir(dest_dir)
                target_filename = os.path.basename(wim_path)
                for f in dir_contents:
                    if f.lower() == target_filename.lower():
                        actual_path = os.path.join(dest_dir, f)
                        _log(f"目标文件存在，先删除以释放空间: {actual_path}")
                        try:
                            os.remove(actual_path)
                            _log("旧文件已删除")
                        except PermissionError:
                            _log("权限不足，尝试 cmd del...")
                            subprocess.Popen(
                                f'del /F /Q "{actual_path}"',
                                shell=True,
                                creationflags=subprocess.CREATE_NO_WINDOW
                            ).communicate()
                        break
            except Exception as e:
                _log(f"检查目录内容时出错: {e}")

            # 3. 检查磁盘空间（至少需要 WIM 大小的 1.1 倍）
            wim_size = os.path.getsize(wim_path)
            try:
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(dest_dir),
                    ctypes.byref(free_bytes),
                    None,
                    None
                )
                free_space = free_bytes.value
                wim_mb = wim_size / (1024 * 1024)
                free_mb = free_space / (1024 * 1024)
                _log(f"WIM大小: {wim_mb:.1f} MB, 目标磁盘可用: {free_mb:.1f} MB")
                if free_space < wim_size * 1.1:
                    return False, (
                        f"目标磁盘空间不足！\n\n"
                        f"WIM文件大小: {wim_mb:.1f} MB\n"
                        f"目标磁盘可用空间: {free_mb:.1f} MB"
                    )
            except Exception as e:
                _log(f"检查磁盘空间时出错: {e}")

            # 4. 复制文件（shutil.copy2 失败则回退 cmd copy /Y）
            _log(f"复制: {wim_path} -> {dest_path}")
            try:
                shutil.copy2(wim_path, dest_path)
            except PermissionError:
                _log("shutil.copy2 失败，尝试 cmd copy...")
                p = subprocess.Popen(
                    f'copy /Y "{wim_path}" "{dest_path}"',
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                _, err = p.communicate()
                if p.returncode != 0:
                    return False, f"复制失败: {err.decode('gbk', errors='replace')}"

            _log(f"复制成功: {dest_path}")
            return True, dest_path

        except PermissionError as e:
            return False, f"权限不足，无法复制到: {dest_dir}\n\n错误: {e}"
        except Exception as e:
            return False, f"复制失败: {e}"

    # ==============================================================
    # 打开 ESP 分区文件夹（系统限制兜底）
    # 说明: Win10/11 隔离 mountvol 挂载的 ESP 盘符，explorer 打不开属系统限制
    #       推荐用户用内置 IsBoot 目录列表进行文件管理（读/删）
    # ==============================================================

    def open_esp_folder(self, sub_path="IsBoot"):
        """打开 ESP 分区的指定子目录

        说明:
          - Win10/11 系统层面隔离了 mountvol 挂载的 ESP 盘符，资源管理器会报"位置不可用"
          - 推荐用户用软件内置的 IsBoot 列表进行文件管理（读取/多选删除）
          - 本方法仅作为兜底尝试：若 Z:\\EFI 可由 os.startfile 打开则打开，否则提示限制

        返回: (bool, str)
        """
        try:
            boot_env = self.detect_boot_environment()

            # ===== BIOS 环境：直接打开 =====
            if boot_env.get('boot_mode') != 'uefi':
                sys_drive = boot_env.get('target_drive') or self._get_sys_drive()
                full = os.path.join(sys_drive, sub_path.lstrip("\\"))
                if not os.path.exists(full):
                    try:
                        os.makedirs(full, exist_ok=True)
                    except OSError:
                        pass
                if os.path.exists(full):
                    try:
                        os.startfile(full)
                        return True, f"已打开: {full}"
                    except Exception as e:
                        return False, f"打开文件夹失败: {e}"
                else:
                    return False, f"路径不存在: {full}"

            # ===== UEFI 环境：系统限制，仅作尝试 =====
            # 确保 ESP 已挂载（纯 mountvol，无扫盘）
            if not os.path.exists("Z:\\EFI"):
                self.ensure_efi_mounted(boot_env)

            full = os.path.join("Z:\\", sub_path.lstrip("\\"))
            if not os.path.exists(full):
                try:
                    os.makedirs(full, exist_ok=True)
                except OSError:
                    pass

            # 尝试打开文件夹 —— 即使 Python 能看到目录，explorer 也可能报"位置不可用"
            try:
                os.startfile(full)
                self._log(f"已尝试打开: {full}（若资源管理器提示位置不可用，属系统限制）")
                return True, f"已尝试打开: {full}"
            except Exception as e:
                self._log(f"打开文件夹失败: {e}")
                return False, f"打开文件夹失败: {e}"

        except Exception as e:
            self._log(f"open_esp_folder 出错: {e}")
            return False, str(e)