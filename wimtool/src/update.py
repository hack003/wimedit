# -*- coding: utf-8 -*-
"""
程序自动更新模块
功能：检查更新、下载新版本、自动替换运行中的程序

版本信息来源：Gitee Releases（https://gitee.com/hack003/wim-tools/releases）
  - 发布标签 tag_name（如 v1.0.3.27）作为版本号
  - 发布说明 body 作为更新日志
  - 发布附件 assets 中的 exe 作为下载地址

内部统一信息结构：
  latest_version : 版本号，如 "1.0.3.27"
  download_url   : 新版本 exe 的下载地址
  update_log     : 更新说明（可选）
  force_update   : 是否强制更新（可选，预留字段）
"""

import os
import sys
import json
import shutil
import threading
import subprocess
import time
import ssl
import re
import urllib.request
import urllib.error
import urllib.parse

# 忽略自签名证书 / 网络代理导致的 SSL 验证问题
try:
    _ssl_context = ssl._create_unverified_context()
except AttributeError:
    try:
        _ssl_context = ssl.create_default_context()
        _ssl_context.check_hostname = False
        _ssl_context.verify_mode = ssl.CERT_NONE
    except Exception:
        _ssl_context = None
except Exception:
    _ssl_context = None

# 同时设置全局默认 SSL 上下文，确保重定向后的 HTTPS 请求也跳过验证
if _ssl_context is not None:
    try:
        ssl._create_default_https_context = lambda: _ssl_context
    except Exception:
        pass

# Gitee 仓库信息（发布版来源）
GITEE_OWNER = "hack003"
GITEE_REPO = "wim-tools"

# Gitee Releases API（取最新发布）
RELEASES_API_URL = (
    "https://gitee.com/api/v5/repos/" + GITEE_OWNER + "/" + GITEE_REPO + "/releases"
)

# 发布页地址（供提示信息使用）
RELEASES_PAGE_URL = "https://gitee.com/" + GITEE_OWNER + "/" + GITEE_REPO + "/releases"

# 发布附件中可执行文件的名称（找不到时退化为匹配 .exe 后缀）
EXPECTED_ASSET_NAME = "WIMTool.exe"

# 程序版本号（由 app_version.py 统一管理，改版本号请修改 app_version.py）
from app_version import VERSION_STR as APP_VERSION


def get_current_version():
    """获取当前程序版本号"""
    return APP_VERSION


def _version_tuple(v):
    """将版本号字符串转换为可比较的元组（支持任意段数，默认最少 4 段，不足补 0）"""
    try:
        parts = [int(x) for x in str(v).split(".")]
        while len(parts) < 4:
            parts.append(0)
        return tuple(parts)
    except (TypeError, ValueError):
        return (0, 0, 0, 0)
def _is_binary_content(headers, peek_bytes=None):
    """判断响应是否是二进制文件（而非 HTML 页面）"""
    ctype = ""
    try:
        ctype = str(headers.get("Content-Type", "")).lower()
    except Exception:
        ctype = ""
    if "html" in ctype or "xml" in ctype or "json" in ctype or "text/plain" in ctype:
        return False
    if "application" in ctype or "octet-stream" in ctype or "binary" in ctype:
        return True
    if peek_bytes is not None:
        if peek_bytes.startswith(b"<") or peek_bytes.startswith(b"<!"):
            return False
        if len(peek_bytes) >= 2 and peek_bytes[0:2] == b"MZ":
            return True
    return None


def _extract_download_urls(html_text, base_url):
    """从 HTML 文本中尝试提取真实下载链接"""
    candidates = []
    try:
        text = html_text
        meta_refresh = re.search(
            r'<meta[^>]+http-equiv\s*=\s*["\']?\s*refresh[^>]*content\s*=\s*["\']?\s*(\d+)\s*;\s*url\s*=\s*([^"\'>]+)',
            text, re.IGNORECASE
        )
        if not meta_refresh:
            meta_refresh = re.search(
                r'<meta[^>]+content\s*=\s*["\']?\s*(\d+)\s*;\s*url\s*=\s*([^"\'>]+)[^>]*http-equiv\s*=\s*["\']?\s*refresh',
                text, re.IGNORECASE
            )
        if meta_refresh:
            raw_url = meta_refresh.group(2).strip().strip("\"'")
            resolved = urllib.parse.urljoin(base_url, raw_url)
            candidates.append(resolved)

        for match in re.finditer(r'<a[^>]+href\s*=\s*["\']([^"\']+)["\'][^>]*>', text, re.IGNORECASE):
            href = match.group(1).strip()
            if not href or href.startswith("#") or href.startswith("javascript"):
                continue
            lowered = href.lower()
            if ".exe" in lowered or "download" in lowered or lowered.endswith(".zip"):
                resolved = urllib.parse.urljoin(base_url, href)
                if resolved not in candidates:
                    candidates.append(resolved)

        for match in re.finditer(
            r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', text, re.IGNORECASE
        ):
            raw_url = match.group(1).strip()
            resolved = urllib.parse.urljoin(base_url, raw_url)
            if resolved not in candidates:
                candidates.append(resolved)
    except Exception:
        pass
    return candidates


def _http_get(url, referer=None, timeout=60):
    """发起 HTTP GET，返回 (response, final_url)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=timeout, context=_ssl_context)
    except urllib.error.URLError as e:
        raise RuntimeError("无法连接到下载服务器：" + str(e))
    final_url = response.geturl()
    return response, final_url


def _download_file(url, save_path, progress_callback=None, referer=None):
    """
    下载文件（智能识别 HTML 下载页 → 从中提取真实链接再下载）。
    最多尝试 5 层重定向/链接解析。
    """
    tried_urls = set()
    current_url = url
    current_referer = referer
    attempt = 0

    while attempt < 5:
        attempt += 1
        if current_url in tried_urls:
            break
        tried_urls.add(current_url)

        response, final_url = _http_get(current_url, referer=current_referer)

        try:
            total_size = response.headers.get("Content-Length")
            if total_size is not None:
                try:
                    total_size = int(total_size)
                except ValueError:
                    total_size = None

            peek = response.read(512)
            is_binary = _is_binary_content(response.headers, peek)

            if is_binary is False or (is_binary is None and peek.startswith(b"<")):
                html_text = peek + response.read()
                response.close()
                try:
                    decoded = None
                    for enc in ["utf-8", "utf-8-sig", "gbk", "latin-1"]:
                        try:
                            decoded = html_text.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    if decoded is None:
                        decoded = html_text.decode("utf-8", errors="replace")
                except Exception:
                    decoded = ""
                # 检测服务端错误信息（下载限制、链接失效等）
                _lower_html = decoded.lower()
                if "exceeded" in _lower_html and ("limit" in _lower_html or "download" in _lower_html):
                    raise RuntimeError("下载链接已超过托管服务的下载次数限制，请更换下载直链。")
                if "not found" in _lower_html or "404" in _lower_html:
                    raise RuntimeError("下载链接已失效（文件未找到），请更新下载地址。")
                if "forbidden" in _lower_html or "403" in _lower_html:
                    raise RuntimeError("下载链接被拒绝访问（403），请检查链接权限。")
                candidates = _extract_download_urls(decoded, final_url)
                if candidates:
                    current_referer = final_url
                    current_url = candidates[0]
                    continue
                raise RuntimeError(
                    "下载链接返回的是网页而不是文件内容。\n"
                    "该下载站可能需要人工点击确认下载，或请换用能直接返回文件的直链。"
                )

            block_size = 65536
            downloaded = len(peek)

            with open(save_path, "wb") as f:
                f.write(peek)
                while True:
                    block = response.read(block_size)
                    if not block:
                        break
                    f.write(block)
                    downloaded += len(block)
                    if progress_callback:
                        try:
                            progress_callback(downloaded, total_size)
                        except Exception:
                            pass

            response.close()
            return downloaded
        except RuntimeError:
            try:
                response.close()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                response.close()
            except Exception:
                pass
            raise RuntimeError("下载时出错：" + str(e))

    raise RuntimeError("多次尝试后仍无法从该链接下载到有效文件。")



def _normalize_version(raw):
    """把发布标签统一成纯数字版本号：v1.0.3.27 / 1.0.3.27 / V1.0.3.27 → 1.0.3.27"""
    text = str(raw or "").strip()
    if not text:
        return ""
    text = text.lstrip("vV").strip()
    match = re.match(r"\d+(?:\.\d+)*", text)
    return match.group(0) if match else text


def _pick_asset(assets):
    """从发布附件列表中挑出 exe 下载地址，优先精确名称匹配。"""
    if not isinstance(assets, list):
        return ""
    fallback = ""
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url:
            continue
        if name.casefold() == EXPECTED_ASSET_NAME.casefold():
            return url
        if name.lower().endswith(".exe") and not fallback:
            fallback = url
    return fallback


def _fetch_version_info():
    """
    从 Gitee Releases 获取最新发布信息，并转换为统一的版本信息结构。
    只取正式发布（跳过 prerelease），按创建时间倒序。
    """
    try:
        _t = str(int(time.time() * 1000))
        url = RELEASES_API_URL + "?page=1&per_page=20&direction=desc&_t=" + _t
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        response = urllib.request.urlopen(req, timeout=20, context=_ssl_context)
        data = response.read()

        text = None
        for enc in ["utf-8", "utf-8-sig", "gbk", "latin-1"]:
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = data.decode("utf-8", errors="replace")

        text = text.strip()
        if text.startswith("<"):
            raise RuntimeError(
                "Gitee 接口返回的是网页而不是 JSON，可能是接口地址变更或访问受限。\n"
                "请手动前往发布页下载：" + RELEASES_PAGE_URL
            )

        releases = json.loads(text)
        if not isinstance(releases, list):
            raise RuntimeError("Gitee Releases 接口返回内容格式异常")

        latest = None
        for release in releases:
            if not isinstance(release, dict):
                continue
            if release.get("prerelease"):
                continue
            if _normalize_version(release.get("tag_name")):
                latest = release
                break

        if latest is None:
            raise RuntimeError(
                "Gitee 上暂未找到可用的正式发布版本。\n"
                "请确认已在发布页上传新版本：" + RELEASES_PAGE_URL
            )

        download_url = _pick_asset(latest.get("assets"))
        if not download_url:
            raise RuntimeError(
                "最新发布（" + str(latest.get("tag_name")) + "）中未找到 exe 附件。\n"
                "请前往发布页确认附件已上传：" + RELEASES_PAGE_URL
            )

        return {
            "latest_version": _normalize_version(latest.get("tag_name")),
            "download_url": download_url,
            "update_log": latest.get("body") or "",
            "force_update": False,
            "release_name": latest.get("name") or "",
            "release_time": latest.get("created_at") or "",
        }
    except json.JSONDecodeError as e:
        raise RuntimeError("Gitee Releases 接口返回内容不是合法 JSON：" + str(e))
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError("获取 Gitee 发布信息失败：" + str(e))


def check_update():
    """
    检查是否有新版本
    返回：(has_update, latest_version, version_info)
    """
    info = _fetch_version_info()

    remote_version = info.get("latest_version")
    if not remote_version:
        raise RuntimeError("Gitee 发布信息中缺少版本号（发布标签 tag_name 为空）")

    current = _version_tuple(APP_VERSION)
    remote = _version_tuple(remote_version)
    has_update = remote > current

    return has_update, str(remote_version), info


def _get_app_exe_path():
    """获取当前运行的可执行文件路径"""
    if getattr(sys, "frozen", False):
        return sys.executable
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "WIMTool.exe")


def _generate_updater_script(new_exe_path, old_exe_path, temp_dir):
    """
    生成一个临时 BAT 脚本，用于在当前程序退出后自动替换旧文件并启动新程序。

    核心修复（针对 "Failed to load Python DLL" / python38.dll 被过早删除问题）：
      1) 用 copy /y 代替 move /y：move 只是改 NTFS 元数据，旧文件属性/ADS 保留；
         copy 生成全新文件，磁盘缓存更干净，Defender 扫描更可预测
      2) copy 后每 2 秒 dir 一次目标文件——强制 Windows 完成文件缓存、写入磁盘、
         完成 on-access 扫描；比单纯 timeout 更有效
      3) 仅精准清理旧进程自身的 _MEI 目录（用旧进程 PID 精确匹配），
         绝不使用 _MEI* 通配符——避免误删新进程正在解压中的 DLL
      4) 启动新 exe 后智能等待：轮询新进程的 _MEI 目录，直到 python38.dll 出现且
         文件大小稳定（连续 2 次读取相同），确保 bootloader 解压完成后再执行任何清理
      5) 用 explorer.exe 启动新 exe：explorer.exe 是用户 shell，在用户上下文中启动进程，
         与用户手动双击行为完全一致，绕过 cmd.exe start 命令触发的额外安全检查
      6) 所有清理操作（temp_dir / BAT 自删除）延迟到新进程解压稳定后执行
    """
    old_pid = os.getpid()
    system_temp = os.environ.get("TEMP") or os.environ.get("TMP") or os.path.dirname(temp_dir)
    bat_name = "_wim_tool_updater_" + str(old_pid) + "_" + str(int(time.time() * 1000)) + ".bat"
    updater_bat = os.path.join(system_temp, bat_name)

    old_dir = os.path.dirname(old_exe_path)
    old_name = os.path.basename(old_exe_path)

    # BAT 脚本：按步骤生成（避免 Python 字符串拼接和 batch 特殊字符冲突）
    # 启用延迟扩展（delayed expansion）：让 if/for 块内的 !var! 在运行时展开，
    # 而不是整行解析时一次性展开——这是智能等待逻辑正确工作的关键。
    lines = []
    lines.append("@echo off")
    lines.append("setlocal enabledelayedexpansion")
    lines.append("chcp 65001 >nul")
    lines.append("cd /d \"" + system_temp + "\"")
    # 第1步：等待旧进程完全退出，释放文件句柄（launch_updater 在 destroy 后调用，进程基本已退出）
    lines.append("timeout /t 2 /nobreak >nul")
    # 第2步：多次删除旧 exe（最多 8 次 × 1秒）
    lines.append("set _retry=0")
    lines.append(":deleteloop")
    lines.append("del /f /q \"" + old_exe_path + "\" 2>nul")
    lines.append("if exist \"" + old_exe_path + "\" (")
    lines.append("    set /a _retry+=1")
    lines.append("    if !_retry! lss 8 (")
    lines.append("        timeout /t 1 /nobreak >nul")
    lines.append("        goto deleteloop")
    lines.append("    )")
    lines.append(")")
    # 第3步：用 copy /y 把新 exe 写到目标位置（生成全新文件）
    lines.append("copy /y \"" + new_exe_path + "\" \"" + old_exe_path + "\" >nul")
    # 第4步：验证 copy 成功
    lines.append("if not exist \"" + old_exe_path + "\" (")
    lines.append("    copy /y \"" + new_exe_path + "\" \"" + old_exe_path + "\" >nul")
    lines.append(")")
    # 第5步：关键等待 + 每 2 秒 dir 强制文件缓存刷新（3 次 ≈ 6 秒）
    # 加上 Python 层下载后已做了文件预热，这里不需要等 10 秒
    lines.append("timeout /t 2 /nobreak >nul")
    lines.append("dir \"" + old_exe_path + "\" >nul")
    lines.append("timeout /t 2 /nobreak >nul")
    lines.append("dir \"" + old_exe_path + "\" >nul")
    lines.append("timeout /t 2 /nobreak >nul")
    lines.append("dir \"" + old_exe_path + "\" >nul")
    # 第6步：精准清理旧进程的 _MEI 目录（用旧进程 PID 精确匹配，绝不 _MEI* 通配）
    # 注意：PyInstaller 的 _MEI 目录名格式为 _MEI<PID><随机数字>，用前缀匹配即可命中
    lines.append("for /d %%d in (\"" + system_temp + "\\_MEI" + str(old_pid) + "*\") do (")
    lines.append("    rd /s /q \"%%d\" 2>nul")
    lines.append(")")
    # 第7步：启动前先记录当前 _MEI 目录快照（用于后续判断哪些是新进程创建的）
    lines.append("set _mei_snapshot=" + system_temp + "\\_mei_snap_" + str(old_pid) + "_" + str(int(time.time())) + ".txt")
    lines.append("dir /b \"" + system_temp + "\\_MEI*\" 2>nul > \"!_mei_snapshot!\"")
    # 第8步：用 explorer.exe 启动新程序（在用户 shell 上下文中，与手动双击一致）
    lines.append("explorer.exe \"" + old_exe_path + "\"")
    # 第9步：智能等待新进程解压完成（关键修复：确保 python38.dll 解压稳定后再继续）
    # 策略：每隔 1 秒扫描 %TEMP% 下新出现的 _MEI 目录，检测其中是否有 python38.dll，
    #       且文件大小连续 2 次保持不变（表明解压完成，文件不再被写入）。
    #       最多等待 30 秒，超时则认为启动已完成（避免 BAT 无限等待）。
    # 注意：所有变量引用使用 !var! 语法（延迟扩展），确保在循环/条件块中能读取最新值。
    lines.append("set _mei_wait=0")
    lines.append("set _mei_prev_size=0")
    lines.append("set _mei_stable_count=0")
    lines.append(":meiwaitloop")
    lines.append("set _mei_dll_path=")
    lines.append("for /f \"delims=\" %%d in ('dir /b /ad \"" + system_temp + "\\_MEI*\" 2^>nul') do (")
    lines.append("    findstr /c:\"%%d\" \"!_mei_snapshot!\" >nul 2>nul")
    lines.append("    if errorlevel 1 (")
    lines.append("        if exist \"" + system_temp + "\\%%d\\python38.dll\" (")
    lines.append("            set _mei_dll_path=\"" + system_temp + "\\%%d\\python38.dll\"")
    lines.append("        )")
    lines.append("    )")
    lines.append(")")
    lines.append("if defined _mei_dll_path (")
    lines.append("    for %%f in (!_mei_dll_path!) do set _mei_curr_size=%%~zf")
    lines.append("    if \"!_mei_prev_size!\"==\"0\" (")
    lines.append("        set _mei_prev_size=!_mei_curr_size!")
    lines.append("    ) else (")
    lines.append("        if \"!_mei_curr_size!\"==\"!_mei_prev_size!\" (")
    lines.append("            set /a _mei_stable_count+=1")
    lines.append("        ) else (")
    lines.append("            set _mei_stable_count=0")
    lines.append("            set _mei_prev_size=!_mei_curr_size!")
    lines.append("        )")
    lines.append("    )")
    lines.append("    if !_mei_stable_count! geq 2 goto meidone")
    lines.append(")")
    lines.append("if !_mei_wait! lss 30 (")
    lines.append("    set /a _mei_wait+=1")
    lines.append("    timeout /t 1 /nobreak >nul")
    lines.append("    goto meiwaitloop")
    lines.append(")")
    lines.append(":meidone")
    # 第10步：检测到解压完成后，额外等待 3 秒让 Python 解释器完成初始化（加载 DLL、初始化 tk 等）
    lines.append("timeout /t 3 /nobreak >nul")
    # 第11步：清理快照文件
    lines.append("if exist \"!_mei_snapshot!\" (del /f /q \"!_mei_snapshot!\" 2>nul)")
    # 第12步：清理临时下载目录（此时新进程已完全启动，解压目录不受影响）
    lines.append("if exist \"" + temp_dir + "\" (rd /s /q \"" + temp_dir + "\" 2>nul)")
    # 第13步：BAT 自删除（endlocal 确保变量不污染环境）
    lines.append("endlocal")
    lines.append("del /f /q \"" + updater_bat + "\" 2>nul")

    content = "\r\n".join(lines) + "\r\n"
    with open(updater_bat, "w", encoding="utf-8", errors="replace") as f:
        f.write(content)
    return updater_bat


def download_and_apply_update(progress_callback=None, log_callback=None):
    """
    下载并执行自动更新。
    """
    def _log(msg):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    _log("正在从 Gitee Releases 获取版本信息...")
    has_update, latest_version, info = check_update()
    if not has_update:
        return {
            "success": False,
            "updater_bat": None,
            "message": "当前版本已是最新版本（" + APP_VERSION + "）"
        }
    _log("发现新版本：" + str(latest_version) + "，开始下载...")

    # 使用 Gitee 发布附件中的下载地址
    url = info.get("download_url")
    if not url:
        raise RuntimeError("Gitee 发布信息中缺少下载地址，请前往发布页手动下载：" + RELEASES_PAGE_URL)
    url = str(url).strip().strip("`").strip("'").strip('"')

    # 准备临时下载目录（放到系统 %TEMP%，避免污染程序目录）
    system_temp = os.environ.get("TEMP") or os.environ.get("TMP") or os.path.dirname(_get_app_exe_path())
    temp_dir = os.path.join(system_temp, "_wim_update_temp_" + str(int(time.time())))
    os.makedirs(temp_dir, exist_ok=True)
    new_exe = os.path.join(temp_dir, "WIMTool.new.exe")

    try:
        _download_file(url, new_exe, progress_callback=progress_callback)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("下载新版本失败：" + str(e))

    size = 0
    try:
        size = os.path.getsize(new_exe)
    except OSError:
        pass
    if size < 100 * 1024:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("下载的文件异常（小于 100KB），请稍后重试或手动下载")

    _log("新版本已下载，大小：" + "{:.2f}".format(size / (1024 * 1024)) + " MB")

    # ========== 下载后关键修复：确保文件已刷入磁盘 + 去除 Zone.Identifier ADS
    _log("正在校验文件完整性...")

    # 1) 显式 flush：打开文件并 force 写入缓存到磁盘，避免 Defender 还在扫描时立即使用
    try:
        fh = open(new_exe, "rb")
        fh.seek(0, 2)
        fh.close()
    except Exception:
        pass

    # 2) 去除 Zone.Identifier ADS（如果下载文件被 Windows 标记为来自 Internet 区域）
    try:
        ads_path = new_exe + ":Zone.Identifier"
        if os.path.exists(ads_path):
            for _r in range(3):
                try:
                    os.remove(ads_path)
                    break
                except Exception:
                    time.sleep(0.2)
    except Exception:
        pass

    # 3) 验证文件可正常读取（读全部字节，做一个完整性校验）
    try:
        with open(new_exe, "rb") as f:
            head = f.read(4)
        # PE/DOS header: MZ\x90\x00
        if head[:2] != b"MZ":
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError("下载的文件不是有效的 exe（缺少 MZ 头），请稍后重试")
    except RuntimeError:
        raise
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("下载的文件无法读取：" + str(e))

    _log("文件校验通过")

    # 文件预热：主动读取文件信息多次，让 Windows Defender 在此期间完成 on-access 扫描
    # 这样 BAT 中的等待时间可以更短（从 ~10s 减到 ~6s）
    try:
        for _w in range(3):
            if os.path.exists(new_exe):
                _ = os.path.getsize(new_exe)
                _ = os.path.getmtime(new_exe)
            time.sleep(0.8)
    except Exception:
        pass

    old_exe = _get_app_exe_path()
    updater_bat = _generate_updater_script(new_exe, old_exe, temp_dir)
    _log("已生成更新脚本")

    return {
        "success": True,
        "updater_bat": updater_bat,
        "message": "更新包已准备就绪，即将退出当前程序并执行更新。"
    }


def launch_updater(updater_bat):
    """启动 BAT 更新脚本，不等待其结束。使用 cmd.exe 直接执行 bat 文件。"""
    try:
        # 使用 shell=False + 列表参数方式。
        # 这样 Python 会直接调用 CreateProcessW Unicode API，
        # 中文/Unicode 路径可被正确传递，不受系统代码页影响。
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE，不显示 cmd 黑框
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(
            ["cmd.exe", "/c", updater_bat],
            shell=False,
            close_fds=True,
            startupinfo=startupinfo,
            creationflags=creationflags
        )
        return True
    except Exception:
        return False


class UpdateChecker:
    """UI 侧高层 API，以线程方式异步执行"""

    def __init__(self, root, log_callback=None, status_callback=None,
                 progress_callback=None, toast_callback=None):
        self.root = root
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.toast_callback = toast_callback
        self._is_checking = False
        self._is_updating = False

    def _log(self, msg):
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                pass

    def _set_status(self, msg):
        if self.status_callback:
            try:
                self.status_callback(msg)
            except Exception:
                pass

    def _toast(self, msg, kind="info"):
        if self.toast_callback:
            try:
                self.toast_callback(msg, kind)
            except Exception:
                pass

    def _set_progress(self, value, text=""):
        if self.progress_callback:
            try:
                self.progress_callback(value, text)
            except Exception:
                pass

    def is_busy(self):
        return self._is_checking or self._is_updating

    def check_update_async(self, on_result_callback=None):
        if self._is_checking:
            return
        self._is_checking = True
        self._set_status("正在检查更新...")
        self._log("正在检查更新...")

        def _worker():
            try:
                has_update, latest_version, info = check_update()
                message = ""
                update_log_text = ""
                if has_update:
                    update_log_text = info.get("update_log") or info.get("release_note") or ""
                    message = "发现新版本：" + str(latest_version) + "（当前 " + APP_VERSION + "）"
                    if update_log_text:
                        message = message + "\n更新说明：" + str(update_log_text)
                else:
                    message = "当前已是最新版本（" + APP_VERSION + "）"

                def _done():
                    self._set_status(message.split("\n")[0])
                    self._log(message.replace("\n", " "))
                    if on_result_callback:
                        try:
                            on_result_callback(has_update, latest_version, message, update_log_text, info)
                        except Exception:
                            pass
                    self._is_checking = False

                self.root.after(0, _done)
            except Exception as e:
                err_msg = "检查更新失败：" + str(e)

                def _err():
                    self._set_status(err_msg)
                    self._log(err_msg)
                    if on_result_callback:
                        try:
                            on_result_callback(False, None, err_msg, "", {})
                        except Exception:
                            pass
                    self._is_checking = False

                self.root.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def do_update_async(self, on_finish_callback=None):
        if self._is_updating:
            return
        self._is_updating = True
        self._set_status("正在下载新版本...")
        self._log("开始下载新版本...")
        self._set_progress(0, "准备下载")

        start_time = time.time()

        def _prog_cb(downloaded, total):
            if total and total > 0:
                percent = downloaded / total * 100
                speed = downloaded / max(time.time() - start_time, 0.001)
                remain = (total - downloaded) / max(speed, 1)
                self.root.after(0, lambda: self._set_progress(
                    percent,
                    "{:.1f}%  {:.2f}MB/s  剩余{:.0f}s".format(
                        percent, speed / 1048576, remain)
                ))
            else:
                seconds = int(time.time() - start_time)
                self.root.after(0, lambda: self._set_progress(
                    min(seconds * 2, 99),
                    "{:.2f}MB 已下载".format(downloaded / 1048576)
                ))

        def _worker():
            try:
                result = download_and_apply_update(
                    progress_callback=_prog_cb,
                    log_callback=lambda m: self.root.after(0, lambda: self._log(m)),
                )
            except Exception as e:
                result = {"success": False, "updater_bat": None, "message": str(e)}

            success = result.get("success", False)
            message = result.get("message", "")
            updater_bat = result.get("updater_bat")

            def _done():
                if success:
                    self._set_progress(100, "下载完成")
                    self._toast("更新包下载完成，将关闭当前程序进行更新", "success")
                else:
                    self._set_progress(0, "")
                    self._toast("更新失败：" + message, "error")

                self._log(message)
                self._is_updating = False
                if on_finish_callback:
                    try:
                        on_finish_callback(success, message, updater_bat)
                    except Exception:
                        pass

            self.root.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()