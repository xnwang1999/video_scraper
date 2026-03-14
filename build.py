#!/usr/bin/env python3
"""
构建脚本：自动下载 ffmpeg 静态二进制 + PyInstaller 打包。
在目标平台上运行即可生成对应平台的可执行文件。

用法：
    python build.py                     # 默认 onefile CLI 版本，自动下载 ffmpeg
    python build.py --gui               # 构建 GUI 版本
    python build.py --onedir            # onedir 模式（更快启动）
    python build.py --use-system-ffmpeg # 用系统已安装的 ffmpeg
    python build.py --no-ffmpeg         # 不捆绑 ffmpeg
"""

import argparse
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

FFMPEG_URLS = {
    "linux_x86_64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    "linux_aarch64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
    "darwin_x86_64": "https://evermeet.cx/ffmpeg/ffmpeg-7.1.1.zip",
    "darwin_arm64": "https://evermeet.cx/ffmpeg/ffmpeg-7.1.1.zip",
    "windows_amd64": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
}

ROOT = Path(__file__).resolve().parent
FFMPEG_DIR = ROOT / "ffmpeg_bin"


def detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        arch = "aarch64" if machine in ("aarch64", "arm64") else "x86_64"
        return f"linux_{arch}"
    elif system == "darwin":
        arch = "arm64" if machine == "arm64" else "x86_64"
        return f"darwin_{arch}"
    elif system == "windows":
        return "windows_amd64"
    else:
        raise RuntimeError(f"不支持的平台: {system} {machine}")


def copy_system_ffmpeg() -> Path:
    """复制系统 ffmpeg 到 ffmpeg_bin 目录。"""
    system_ffmpeg = shutil.which("ffmpeg")
    if not system_ffmpeg:
        raise RuntimeError("系统未安装 ffmpeg，请先安装或使用默认的自动下载模式")

    FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    target = FFMPEG_DIR / exe_name
    print(f"复制系统 ffmpeg: {system_ffmpeg} -> {target}")
    shutil.copy2(system_ffmpeg, target)
    if not sys.platform == "win32":
        target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return target


def download_ffmpeg(plat: str) -> Path:
    """下载平台对应的 ffmpeg 静态二进制。"""
    import requests

    url = FFMPEG_URLS.get(plat)
    if not url:
        raise RuntimeError(f"没有对应平台的 ffmpeg 下载地址: {plat}")

    FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    exe_name = "ffmpeg.exe" if plat.startswith("windows") else "ffmpeg"
    target = FFMPEG_DIR / exe_name

    if target.exists():
        print(f"ffmpeg 已存在: {target}")
        return target

    archive_name = url.rsplit("/", 1)[-1]
    archive_path = FFMPEG_DIR / archive_name
    print(f"下载 ffmpeg: {url}")
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(archive_path, "wb") as fp:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            fp.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  下载进度: {pct}% ({downloaded // (1024*1024)} MB)", end="", flush=True)
    print()

    print("解压 ffmpeg...")
    if archive_name.endswith(".tar.xz"):
        with tarfile.open(archive_path, "r:xz") as tf:
            for member in tf.getmembers():
                if member.name.endswith("/ffmpeg") and member.isfile():
                    member.name = exe_name
                    tf.extract(member, FFMPEG_DIR)
                    break
    elif archive_name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for name in zf.namelist():
                basename = name.rsplit("/", 1)[-1] if "/" in name else name
                if basename in ("ffmpeg", "ffmpeg.exe"):
                    data = zf.read(name)
                    target.write_bytes(data)
                    break

    archive_path.unlink(missing_ok=True)

    if not target.exists():
        raise RuntimeError("ffmpeg 解压失败，未找到 ffmpeg 二进制")

    if not plat.startswith("windows"):
        target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"ffmpeg 就绪: {target}")
    return target


def _common_excludes(gui: bool = False) -> list:
    excludes = [
        "torch", "torchvision", "torchaudio",
        "numpy", "scipy", "sklearn", "pandas",
        "matplotlib", "PIL", "Pillow",
        "IPython", "jupyter", "notebook",
        "test", "unittest",
        "tensorboard", "sympy",
        "nvidia", "triton",
        "openpyxl", "pytest",
    ]
    if not gui:
        excludes.append("tkinter")
    return excludes


def _run_pyinstaller(
    entry: Path,
    name: str,
    onedir: bool,
    ffmpeg_path: Path | None,
    hidden_imports: list,
    excludes: list,
    extra_args: list | None = None,
):
    cmd = [sys.executable, "-m", "PyInstaller", "--name", name]

    if ffmpeg_path:
        sep = ";" if sys.platform == "win32" else ":"
        cmd.extend(["--add-binary", f"{ffmpeg_path}{sep}ffmpeg"])

    for mod in hidden_imports:
        cmd.extend(["--hidden-import", mod])

    cmd.extend(["--noconfirm", "--clean"])

    for mod in excludes:
        cmd.extend(["--exclude-module", mod])

    if extra_args:
        cmd.extend(extra_args)

    cmd.append("--onedir" if onedir else "--onefile")
    cmd.append(str(entry))

    print(f"运行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(ROOT))

    dist = ROOT / "dist"
    if onedir:
        output = dist / name
    else:
        exe_name = f"{name}.exe" if sys.platform == "win32" else name
        output = dist / exe_name

    if output.exists():
        if output.is_dir():
            size = sum(f.stat().st_size for f in output.rglob("*") if f.is_file())
        else:
            size = output.stat().st_size
        print(f"\n构建成功: {output} ({size / (1024 * 1024):.1f} MB)")
    else:
        print(f"\n警告: 未找到输出文件 {output}")


def build(onedir: bool = False, use_system_ffmpeg: bool = False, no_ffmpeg: bool = False, gui: bool = False):
    plat = detect_platform()
    print(f"平台: {plat}")

    ffmpeg_path = None
    if no_ffmpeg:
        print("跳过 ffmpeg 捆绑")
    elif use_system_ffmpeg:
        ffmpeg_path = copy_system_ffmpeg()
    else:
        ffmpeg_path = download_ffmpeg(plat)

    cli_hidden = [
        "yt_dlp", "Crypto", "Crypto.Cipher", "Crypto.Cipher.AES",
        "bs4", "tqdm", "requests", "lxml",
    ]

    if gui:
        print("\n===== 构建 GUI 版本 =====")
        gui_hidden = cli_hidden + ["customtkinter"]
        windowed = ["--windowed"] if sys.platform != "linux" else []
        _run_pyinstaller(
            entry=ROOT / "video_scraper_gui.py",
            name="video_scraper_gui",
            onedir=onedir,
            ffmpeg_path=ffmpeg_path,
            hidden_imports=gui_hidden,
            excludes=_common_excludes(gui=True),
            extra_args=windowed,
        )
    else:
        print("\n===== 构建 CLI 版本 =====")
        _run_pyinstaller(
            entry=ROOT / "video_scraper.py",
            name="video_scraper",
            onedir=onedir,
            ffmpeg_path=ffmpeg_path,
            hidden_imports=cli_hidden,
            excludes=_common_excludes(gui=False),
        )


def main():
    parser = argparse.ArgumentParser(description="Video Scraper 构建脚本")
    parser.add_argument("--onedir", action="store_true", help="onedir 模式（多文件，启动更快）")
    parser.add_argument("--use-system-ffmpeg", action="store_true", help="使用系统已安装的 ffmpeg")
    parser.add_argument("--no-ffmpeg", action="store_true", help="不捆绑 ffmpeg")
    parser.add_argument("--gui", action="store_true", help="构建 GUI 版本（默认构建 CLI 版本）")
    args = parser.parse_args()
    build(onedir=args.onedir, use_system_ffmpeg=args.use_system_ffmpeg, no_ffmpeg=args.no_ffmpeg, gui=args.gui)


if __name__ == "__main__":
    main()
