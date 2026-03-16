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
    python build.py --bundle-node       # 捆绑 Node.js（YouTube 需要）
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

NODE_URLS = {
    "windows_amd64": "https://nodejs.org/dist/v22.16.0/node-v22.16.0-win-x64.zip",
    "linux_x86_64": "https://nodejs.org/dist/v22.16.0/node-v22.16.0-linux-x64.tar.xz",
    "linux_aarch64": "https://nodejs.org/dist/v22.16.0/node-v22.16.0-linux-arm64.tar.xz",
    "darwin_x86_64": "https://nodejs.org/dist/v22.16.0/node-v22.16.0-darwin-x64.tar.gz",
    "darwin_arm64": "https://nodejs.org/dist/v22.16.0/node-v22.16.0-darwin-arm64.tar.gz",
}

ROOT = Path(__file__).resolve().parent
FFMPEG_DIR = ROOT / "ffmpeg_bin"
NODE_DIR = ROOT / "node_bin"


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


def prepare_node(plat: str) -> Path | None:
    """准备 Node.js 二进制：优先复制系统已安装的，否则从网络下载。"""
    import requests as _requests

    NODE_DIR.mkdir(parents=True, exist_ok=True)
    exe_name = "node.exe" if plat.startswith("windows") else "node"
    target = NODE_DIR / exe_name

    if target.exists():
        print(f"node 已存在: {target}")
        return target

    system_node = shutil.which("node")
    if not system_node and sys.platform == "win32":
        candidate = Path(r"C:\Program Files\nodejs\node.exe")
        if candidate.exists():
            system_node = str(candidate)

    if system_node:
        print(f"复制系统 node: {system_node} -> {target}")
        shutil.copy2(system_node, target)
        if not plat.startswith("windows"):
            target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return target

    url = NODE_URLS.get(plat)
    if not url:
        print(f"警告: 没有对应平台的 Node.js 下载地址: {plat}，跳过")
        return None

    archive_name = url.rsplit("/", 1)[-1]
    archive_path = NODE_DIR / archive_name
    print(f"下载 Node.js: {url}")
    resp = _requests.get(url, stream=True, timeout=300)
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

    print("解压 Node.js...")
    if archive_name.endswith((".tar.xz", ".tar.gz")):
        mode = "r:xz" if archive_name.endswith(".tar.xz") else "r:gz"
        with tarfile.open(archive_path, mode) as tf:
            for member in tf.getmembers():
                if member.name.endswith("/bin/node") and member.isfile():
                    member.name = exe_name
                    tf.extract(member, NODE_DIR)
                    break
    elif archive_name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/node.exe"):
                    data = zf.read(name)
                    target.write_bytes(data)
                    break

    archive_path.unlink(missing_ok=True)

    if target.exists():
        if not plat.startswith("windows"):
            target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print(f"Node.js 就绪: {target}")
        return target

    print("警告: Node.js 解压失败，跳过")
    return None


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
    collect_all: list | None = None,
    collect_data: list | None = None,
    collect_submodules: list | None = None,
    extra_args: list | None = None,
    node_path: Path | None = None,
):
    cmd = [sys.executable, "-m", "PyInstaller", "--name", name]

    sep = ";" if sys.platform == "win32" else ":"
    if ffmpeg_path:
        cmd.extend(["--add-binary", f"{ffmpeg_path}{sep}ffmpeg"])
    if node_path:
        cmd.extend(["--add-binary", f"{node_path}{sep}node"])

    for mod in (collect_all or []):
        cmd.extend(["--collect-all", mod])
    for mod in (collect_data or []):
        cmd.extend(["--collect-data", mod])
    for mod in (collect_submodules or []):
        cmd.extend(["--collect-submodules", mod])

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


def build(onedir: bool = False, use_system_ffmpeg: bool = False, no_ffmpeg: bool = False, gui: bool = False, bundle_node: bool = False):
    plat = detect_platform()
    print(f"平台: {plat}")

    ffmpeg_path = None
    if no_ffmpeg:
        print("跳过 ffmpeg 捆绑")
    elif use_system_ffmpeg:
        ffmpeg_path = copy_system_ffmpeg()
    else:
        ffmpeg_path = download_ffmpeg(plat)

    node_path = None
    if bundle_node:
        node_path = prepare_node(plat)

    # 最小依赖：只打包真正用到的
    # - yt_dlp: 必须 collect-all（大量动态加载的 extractor）
    # - bs4: 仅用 html.parser，收子模块但排除 tests/diagnose
    # - certifi: 只收 cacert.pem（SSL 证书）
    # - Crypto.Cipher.AES: 仅 m3u8 AES-128 解密用
    # - lxml 由 yt_dlp/requests 依赖图带入，不单独 hidden-import
    cli_hidden = [
        "Crypto", "Crypto.Cipher", "Crypto.Cipher.AES",
        "bs4", "bs4.builder", "bs4.builder._htmlparser",
        "tqdm", "requests",
    ]
    cli_collect_all = ["yt_dlp"]
    cli_collect_data = ["certifi"]
    cli_collect_submodules = []  # bs4 用 hidden + 上面子模块，避免收进 bs4.tests

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
            collect_all=cli_collect_all + ["customtkinter"],
            collect_data=cli_collect_data,
            collect_submodules=cli_collect_submodules,
            extra_args=windowed,
            node_path=node_path,
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
            collect_all=cli_collect_all,
            collect_data=cli_collect_data,
            collect_submodules=cli_collect_submodules,
            node_path=node_path,
        )


def main():
    parser = argparse.ArgumentParser(description="Video Scraper 构建脚本")
    parser.add_argument("--onedir", action="store_true", help="onedir 模式（多文件，启动更快）")
    parser.add_argument("--use-system-ffmpeg", action="store_true", help="使用系统已安装的 ffmpeg")
    parser.add_argument("--no-ffmpeg", action="store_true", help="不捆绑 ffmpeg")
    parser.add_argument("--gui", action="store_true", help="构建 GUI 版本（默认构建 CLI 版本）")
    parser.add_argument("--bundle-node", action="store_true", help="捆绑 Node.js（YouTube 需要）")
    args = parser.parse_args()
    build(onedir=args.onedir, use_system_ffmpeg=args.use_system_ffmpeg, no_ffmpeg=args.no_ffmpeg, gui=args.gui, bundle_node=args.bundle_node)


if __name__ == "__main__":
    main()
