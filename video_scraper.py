#!/usr/bin/env python3
"""
Video Scraper - 面向公开非加密视频页面的下载与信息提取工具。
核心策略：
1) 优先使用 yt-dlp 处理绝大多数主流站点和通用提取器；
2) 若失败，则回退到页面直链提取 + 直链下载。
"""

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

import requests

try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

try:
    from bs4 import BeautifulSoup

    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import yt_dlp

    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

try:
    from Crypto.Cipher import AES as _AES

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

VIDEO_URL_PATTERNS = [
    r'"(https?://[^"]*\.(?:mp4|m3u8|webm|avi|mkv|flv|mov|m4v)(?:\?[^"]*)?)"',
    r"'(https?://[^']*\.(?:mp4|m3u8|webm|avi|mkv|flv|mov|m4v)(?:\?[^']*)?)'",
    r'src["\']?\s*:\s*["\']([^"\']*\.(?:mp4|m3u8|webm|avi|mkv|flv|mov|m4v)[^"\']*)',
    r'file["\']?\s*:\s*["\']([^"\']*\.(?:mp4|m3u8|webm|avi|mkv|flv|mov|m4v)[^"\']*)',
    r'url["\']?\s*:\s*["\']([^"\']*\.(?:mp4|m3u8|webm|avi|mkv|flv|mov|m4v)[^"\']*)',
]


@dataclass
class VideoInfo:
    """视频信息数据结构"""

    url: str
    platform: str = ""
    title: str = ""
    description: str = ""
    duration: str = ""
    view_count: str = ""
    upload_date: str = ""
    uploader: str = ""
    thumbnail_url: str = ""
    webpage_url: str = ""
    extractor: str = ""
    video_urls: List[str] = None
    tags: List[str] = None
    formats: List[Dict[str, str]] = None
    timestamp: str = ""

    def __post_init__(self):
        if self.video_urls is None:
            self.video_urls = []
        if self.tags is None:
            self.tags = []
        if self.formats is None:
            self.formats = []
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")


def _detect_js_runtimes() -> Dict:
    """检测可用的 JS 运行时（deno/node/bun），供 yt-dlp 使用"""
    runtimes: Dict = {}
    for name in ("deno", "node", "bun"):
        path = shutil.which(name)
        if path:
            runtimes[name] = {}
            continue
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            exe = f"{name}.exe" if sys.platform == "win32" else name
            candidates.append(Path(sys._MEIPASS) / "node" / exe)
        if sys.platform == "win32" and name == "node":
            candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe")
            candidates.append(Path(os.environ.get("LOCALAPPDATA", "")) / "fnm_multishells" / "node.exe")
        for candidate in candidates:
            if candidate.exists():
                runtimes[name] = {"path": str(candidate)}
                break
    return runtimes


def _get_ffmpeg_path() -> str:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
        name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        bundled = base / "ffmpeg" / name
        if bundled.exists():
            return str(bundled)
    return shutil.which("ffmpeg") or "ffmpeg"


class VideoScraper:
    """视频网站爬虫类"""

    def __init__(
        self,
        quality: str = "best",
        browser: Optional[str] = None,
        cookies_file: str = "cookies.txt",
        timeout: int = 30,
        retries: int = 3,
        proxy: Optional[str] = None,
        referer: Optional[str] = None,
        audio_only: bool = False,
        concurrent_fragments: int = 4,
    ):
        self.quality = quality
        self.browser = browser
        self.cookies_file = cookies_file
        self.timeout = timeout
        self.retries = retries
        self.proxy = proxy
        self.referer = referer
        self.audio_only = audio_only
        self.concurrent_fragments = concurrent_fragments

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        if self.referer:
            self.session.headers["Referer"] = self.referer
        if self.proxy:
            self.session.proxies.update({"http": self.proxy, "https": self.proxy})

        if self.cookies_file and Path(self.cookies_file).exists():
            try:
                import http.cookiejar
                cj = http.cookiejar.MozillaCookieJar(self.cookies_file)
                cj.load(ignore_discard=True, ignore_expires=True)
                self.session.cookies.update(cj)
            except Exception:
                pass

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        self.logger = logging.getLogger(__name__)
        self.scraped_videos: List[VideoInfo] = []

    def detect_platform(self, url: str) -> str:
        """检测视频平台类型"""
        domain = urlparse(url).netloc.lower()
        known = [
            "youtube",
            "youtu",
            "bilibili",
            "vimeo",
            "tiktok",
            "instagram",
            "facebook",
            "x.com",
            "twitter",
            "dailymotion",
            "youku",
            "iqiyi",
            "mgtv",
            "douyin",
        ]
        for token in known:
            if token in domain:
                return token
        return "generic"

    def _quality_to_format(self) -> str:
        if self.audio_only:
            return "bestaudio/best"
        quality = str(self.quality).strip().lower()
        m = re.fullmatch(r"(\d{3,4})p", quality)
        if m:
            max_h = m.group(1)
            return f"bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]/best"
        if quality in ("best", "worst"):
            return f"{quality}video+{quality}audio/{quality}"
        return self.quality

    def _build_ydl_opts(self, download: bool = False, output_path: str = "./downloads/") -> Dict:
        opts: Dict = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": self.timeout,
            "retries": 10,
            "fragment_retries": 10,
            "continuedl": True,
            "noprogress": False,
            "concurrent_fragment_downloads": self.concurrent_fragments,
            "http_headers": {"User-Agent": self.session.headers["User-Agent"]},
            "proxy": self.proxy,
            "format": self._quality_to_format(),
            "ffmpeg_location": str(Path(_get_ffmpeg_path()).parent),
        }
        opts["extractor_args"] = {
            "youtube": {"player_client": ["default"]},
            "generic": {"impersonate": [""]},
        }
        opts["js_runtimes"] = _detect_js_runtimes()
        opts["remote_components"] = {"ejs:github"}
        if self.referer:
            opts["referer"] = self.referer
        if self.cookies_file and Path(self.cookies_file).exists():
            opts["cookiefile"] = self.cookies_file
        if self.browser:
            opts["cookiesfrombrowser"] = (self.browser,)

        if download:
            Path(output_path).mkdir(parents=True, exist_ok=True)
            opts["quiet"] = False
            opts["noprogress"] = False
            opts.update(
                {
                    "outtmpl": f"{output_path}/%(title).180B [%(id)s].%(ext)s",
                    "merge_output_format": "mp4",
                    "postprocessors": (
                        [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
                        if self.audio_only
                        else []
                    ),
                }
            )
        return opts

    @staticmethod
    def _normalize_info(info: Dict) -> Dict:
        if info and isinstance(info, dict) and info.get("_type") in {"playlist", "multi_video"}:
            entries = info.get("entries") or []
            for entry in entries:
                if entry:
                    return entry
        return info or {}

    def _build_video_info_from_ytdlp(self, source_url: str, info: Dict) -> VideoInfo:
        normalized = self._normalize_info(info)
        video = VideoInfo(
            url=source_url,
            platform=self.detect_platform(source_url),
            title=normalized.get("title", "") or "",
            description=(normalized.get("description", "") or "")[:1000],
            duration=str(normalized.get("duration", "") or ""),
            view_count=str(normalized.get("view_count", "") or ""),
            upload_date=normalized.get("upload_date", "") or "",
            uploader=normalized.get("uploader", "") or "",
            thumbnail_url=normalized.get("thumbnail", "") or "",
            webpage_url=normalized.get("webpage_url", "") or "",
            extractor=normalized.get("extractor", "") or "",
            tags=(normalized.get("tags") or [])[:20],
        )

        seen = set()
        for fmt in normalized.get("formats") or []:
            fmt_url = fmt.get("url")
            if not fmt_url or fmt_url in seen:
                continue
            seen.add(fmt_url)
            if len(video.video_urls) < 20:
                video.video_urls.append(fmt_url)
            if len(video.formats) < 20:
                video.formats.append(
                    {
                        "format_id": str(fmt.get("format_id", "")),
                        "ext": str(fmt.get("ext", "")),
                        "resolution": str(fmt.get("resolution") or fmt.get("format_note") or ""),
                        "vcodec": str(fmt.get("vcodec", "")),
                        "acodec": str(fmt.get("acodec", "")),
                    }
                )
        return video

    def extract_with_ytdlp(self, url: str) -> Optional[VideoInfo]:
        """使用 yt-dlp 提取视频信息"""
        if not HAS_YTDLP:
            self.logger.warning("yt-dlp 不可用，尝试使用通用直链提取。")
            return None
        try:
            with yt_dlp.YoutubeDL(self._build_ydl_opts(download=False)) as ydl:
                info = ydl.extract_info(url, download=False)
            return self._build_video_info_from_ytdlp(url, info)
        except Exception as exc:
            self.logger.warning(f"yt-dlp 提取失败: {exc}")
            return None

    def _extract_with_requests(self, url: str) -> requests.Response:
        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                self.logger.warning(f"请求失败（{attempt}/{self.retries}）: {exc}")
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 5))
        raise RuntimeError(f"请求失败: {last_error}")

    def extract_generic_video(self, url: str) -> Optional[VideoInfo]:
        """通用视频页面信息提取（回退方案）"""
        try:
            response = self._extract_with_requests(url)
        except Exception as exc:
            self.logger.error(f"页面拉取失败: {exc}")
            return None

        video_info = VideoInfo(url=url, platform=self.detect_platform(url), webpage_url=response.url, extractor="generic")
        if not HAS_BS4:
            self.logger.warning("BeautifulSoup 不可用，仅做最小化正则提取。")
            text = response.text
            matches = []
            for pattern in VIDEO_URL_PATTERNS:
                matches.extend(re.findall(pattern, text, flags=re.IGNORECASE))
            video_info.video_urls = list(dict.fromkeys(matches))[:20]
            return video_info

        soup = BeautifulSoup(response.content, "html.parser")

        title_tag = soup.find("meta", {"property": "og:title"}) or soup.find("title")
        if title_tag:
            video_info.title = (title_tag.get("content") if title_tag.has_attr("content") else title_tag.get_text()).strip()

        desc_tag = soup.find("meta", {"property": "og:description"}) or soup.find("meta", {"name": "description"})
        if desc_tag and desc_tag.get("content"):
            video_info.description = desc_tag.get("content", "")[:1000]

        img_tag = soup.find("meta", {"property": "og:image"})
        if img_tag and img_tag.get("content"):
            video_info.thumbnail_url = img_tag.get("content", "")

        candidates: List[str] = []
        for tag in soup.find_all(["video", "source"]):
            src = tag.get("src")
            if src:
                candidates.append(urljoin(response.url, src))

        for iframe in soup.find_all("iframe", src=True):
            iframe_src = iframe.get("src")
            if iframe_src and any(x in iframe_src for x in ["youtube", "vimeo", "dailymotion", "player"]):
                candidates.append(urljoin(response.url, iframe_src))

        scripts = soup.find_all("script")
        for script in scripts:
            script_content = script.string or script.get_text() or ""
            if not script_content:
                continue
            encoded = re.findall(r"unescape\(['\"](%[0-9a-fA-F%]+)['\"]\)", script_content)
            for item in encoded:
                candidates.append(unquote(item))
            for pattern in VIDEO_URL_PATTERNS:
                matches = re.findall(pattern, script_content, flags=re.IGNORECASE)
                for match in matches:
                    candidates.append(urljoin(response.url, match))

        dedup = []
        seen = set()
        for candidate in candidates:
            if not candidate:
                continue
            if candidate.startswith("//"):
                candidate = f"https:{candidate}"
            if candidate in seen:
                continue
            seen.add(candidate)
            dedup.append(candidate)

        video_info.video_urls = dedup[:20]
        return video_info

    def scrape_video(self, url: str) -> Optional[VideoInfo]:
        """爬取单个视频信息"""
        self.logger.info(f"处理视频: {url}")
        video_info = self.extract_with_ytdlp(url)
        if not video_info:
            video_info = self.extract_generic_video(url)
        if video_info:
            self.scraped_videos.append(video_info)
            self.logger.info(f"提取成功: {video_info.title or '(无标题)'}")
        else:
            self.logger.error(f"提取失败: {url}")
        return video_info

    def scrape_videos(self, urls: List[str]) -> List[VideoInfo]:
        """批量提取视频信息"""
        results = []
        for idx, url in enumerate(urls, start=1):
            self.logger.info(f"进度 {idx}/{len(urls)}")
            item = self.scrape_video(url)
            if item:
                results.append(item)
            if idx < len(urls):
                time.sleep(1)
        return results

    @dataclass
    class M3u8Info:
        ts_urls: List[str]
        method: Optional[str] = None
        key_url: Optional[str] = None
        iv: Optional[bytes] = None
        media_sequence: int = 0

    def _parse_m3u8(self, m3u8_url: str, referer: str) -> "VideoScraper.M3u8Info":
        """解析 m3u8，返回分片列表及加密信息。"""
        headers = {"User-Agent": self.session.headers["User-Agent"], "Referer": referer}
        resp = self.session.get(m3u8_url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        content = resp.text

        base_url = m3u8_url.rsplit("/", 1)[0] + "/"
        method = None
        key_url = None
        iv = None
        media_sequence = 0
        ts_urls: List[str] = []

        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-MEDIA-SEQUENCE"):
                try:
                    media_sequence = int(line.split(":")[1])
                except (IndexError, ValueError):
                    pass
            elif line.startswith("#EXT-X-KEY"):
                m_method = re.search(r'METHOD=([A-Z0-9-]+)', line)
                if m_method:
                    method = m_method.group(1)
                m_uri = re.search(r'URI="([^"]+)"', line)
                if m_uri:
                    key_url = urljoin(base_url, m_uri.group(1))
                m_iv = re.search(r'IV=0x([0-9a-fA-F]+)', line)
                if m_iv:
                    iv = bytes.fromhex(m_iv.group(1).zfill(32))
            elif line and not line.startswith("#"):
                ts_urls.append(urljoin(base_url, line))

        return self.M3u8Info(
            ts_urls=ts_urls, method=method, key_url=key_url,
            iv=iv, media_sequence=media_sequence,
        )

    @staticmethod
    def _decrypt_aes128(data: bytes, key: bytes, iv: bytes) -> bytes:
        cipher = _AES.new(key, _AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(data)
        pad_len = decrypted[-1]
        if 1 <= pad_len <= 16 and decrypted[-pad_len:] == bytes([pad_len]) * pad_len:
            decrypted = decrypted[:-pad_len]
        return decrypted

    def _download_ts_segment(
        self, idx: int, url: str, tmp_dir: Path, referer: str, state: dict, lock: Lock,
        aes_key: Optional[bytes] = None, aes_iv: Optional[bytes] = None,
        media_sequence: int = 0,
    ) -> Tuple[int, bool]:
        """下载单个 ts 分片，可选 AES-128 解密，带重试。"""
        out_path = tmp_dir / f"{idx:06d}.ts"
        headers = {"User-Agent": self.session.headers["User-Agent"], "Referer": referer}
        last_err = ""
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.content
                if not data:
                    raise RuntimeError("empty response")

                if aes_key:
                    if aes_iv:
                        iv = aes_iv
                    else:
                        iv = (media_sequence + idx).to_bytes(16, "big")
                    data = self._decrypt_aes128(data, aes_key, iv)

                out_path.write_bytes(data)
                size = len(data)
                with lock:
                    state["done"] += 1
                    state["bytes"] += size
                return idx, True
            except Exception as exc:
                last_err = str(exc)
                if attempt < 2:
                    time.sleep(1 + attempt)
        with lock:
            state["done"] += 1
            state["failed"] += 1
            if state["failed"] <= 3:
                self.logger.warning(f"分片 {idx} 下载失败: {last_err}")
        return idx, False

    def _download_m3u8(self, m3u8_url: str, output_file: Path, referer: str) -> bool:
        """多线程下载 m3u8 分片（支持 AES-128 解密），再用 ffmpeg 合并为 mp4。"""
        output_file = output_file.with_suffix(".mp4")
        self.logger.info(f"m3u8 下载: {m3u8_url}")

        try:
            info = self._parse_m3u8(m3u8_url, referer)
        except Exception as exc:
            self.logger.warning(f"m3u8 解析失败({exc})，回退 ffmpeg 单线程下载。")
            return self._download_m3u8_ffmpeg(m3u8_url, output_file, referer)

        if not info.ts_urls:
            self.logger.warning("m3u8 未找到 ts 分片，回退 ffmpeg 单线程下载。")
            return self._download_m3u8_ffmpeg(m3u8_url, output_file, referer)

        encrypted = info.method == "AES-128" and info.key_url
        if encrypted and not HAS_CRYPTO:
            self.logger.info("m3u8 使用 AES-128 加密但 pycryptodome 未安装，回退 ffmpeg 单线程。")
            return self._download_m3u8_ffmpeg(m3u8_url, output_file, referer)

        aes_key = None
        if encrypted:
            try:
                headers = {"User-Agent": self.session.headers["User-Agent"], "Referer": referer}
                key_resp = self.session.get(info.key_url, headers=headers, timeout=self.timeout)
                key_resp.raise_for_status()
                aes_key = key_resp.content
                if len(aes_key) != 16:
                    raise ValueError(f"key 长度异常: {len(aes_key)} bytes")
                self.logger.info("AES-128 key 获取成功，多线程下载 + 解密模式")
            except Exception as exc:
                self.logger.warning(f"AES key 获取失败({exc})，回退 ffmpeg 单线程下载。")
                return self._download_m3u8_ffmpeg(m3u8_url, output_file, referer)

        total = len(info.ts_urls)
        mode = "加密" if encrypted else "未加密"
        self.logger.info(f"共 {total} 个{mode}分片，{self.concurrent_fragments} 线程并发下载")

        import hashlib
        out_dir = output_file.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        short_id = hashlib.md5(m3u8_url.encode()).hexdigest()[:8]
        tmp_path = out_dir / f".m3u8_tmp_{short_id}"
        tmp_path.mkdir(parents=True, exist_ok=True)
        try:
            return self._download_m3u8_mt_inner(
                m3u8_url, output_file, referer, info, total, tmp_path,
                aes_key=aes_key,
            )
        finally:
            import shutil as _shutil
            try:
                _shutil.rmtree(tmp_path, ignore_errors=True)
            except Exception:
                pass

    def _download_m3u8_mt_inner(
        self, m3u8_url: str, output_file: Path, referer: str,
        info: "VideoScraper.M3u8Info", total: int, tmp_path: Path,
        aes_key: Optional[bytes] = None,
    ) -> bool:
        """多线程下载内部逻辑，支持 AES-128 解密。"""

        state = {"done": 0, "bytes": 0, "failed": 0}
        lock = Lock()
        cols = shutil.get_terminal_size().columns
        start_ts = time.monotonic()
        prev_bytes = 0
        prev_ts = start_ts
        speed_str = ""

        with ThreadPoolExecutor(max_workers=self.concurrent_fragments) as pool:
            futures = {
                pool.submit(
                    self._download_ts_segment, i, url, tmp_path, referer, state, lock,
                    aes_key=aes_key, aes_iv=info.iv, media_sequence=info.media_sequence,
                ): i
                for i, url in enumerate(info.ts_urls)
            }

            last_print = 0.0
            while True:
                done_count = sum(1 for f in futures if f.done())
                now = time.monotonic()
                if now - last_print >= 1.0:
                    last_print = now
                    with lock:
                        done = state["done"]
                        total_bytes = state["bytes"]
                        failed = state["failed"]
                    dt = now - prev_ts
                    if dt > 0:
                        speed = (total_bytes - prev_bytes) / dt
                        if speed >= 1024 * 1024:
                            speed_str = f"{speed / (1024 * 1024):.1f} MB/s"
                        else:
                            speed_str = f"{speed / 1024:.0f} KB/s"
                    prev_bytes = total_bytes
                    prev_ts = now
                    elapsed = int(now - start_ts)
                    elapsed_str = f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"
                    size_mb = total_bytes / (1024 * 1024)
                    pct = done * 100 // total if total else 0
                    fail_info = f" | 失败 {failed}" if failed else ""
                    status = (
                        f"\r  m3u8 下载中  {done}/{total} ({pct}%)"
                        f" | {size_mb:.1f} MB | 耗时 {elapsed_str}"
                        f" | 速度 {speed_str}{fail_info}"
                    )
                    print(f"{status:<{cols}}", end="", flush=True)
                if done_count >= len(futures):
                    break
                time.sleep(0.3)

        print()

        with lock:
            failed = state["failed"]
            done_bytes = state["bytes"]

        if failed > total * 0.5 or done_bytes == 0:
            self.logger.warning(
                f"多线程下载失败过多 ({failed}/{total})，回退 ffmpeg 单线程下载。"
            )
            return self._download_m3u8_ffmpeg(m3u8_url, output_file, referer)

        existing = [tmp_path / f"{i:06d}.ts" for i in range(total) if (tmp_path / f"{i:06d}.ts").exists()]
        if not existing:
            self.logger.warning("无可用分片，回退 ffmpeg 单线程下载。")
            return self._download_m3u8_ffmpeg(m3u8_url, output_file, referer)

        self.logger.info(f"分片验证: {len(existing)}/{total} 个文件存在")

        concat_file = tmp_path / "concat.txt"
        with open(concat_file, "w") as fp:
            for ts_file in existing:
                escaped = str(ts_file).replace("'", "'\\''")
                fp.write(f"file '{escaped}'\n")

        merge_cmd = [
            _get_ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            str(output_file),
        ]
        self.logger.info(f"合并 {len(existing)}/{total} 个分片...")
        result = subprocess.run(merge_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0 and output_file.exists() and output_file.stat().st_size > 0:
            size_mb = output_file.stat().st_size / (1024 * 1024)
            elapsed = int(time.monotonic() - start_ts)
            self.logger.info(f"下载完成: {output_file} ({size_mb:.1f} MB, 耗时 {elapsed}s)")
            return True

        self.logger.warning(f"ffmpeg 合并失败，回退单线程下载。stderr: {result.stderr[-300:]}")
        return self._download_m3u8_ffmpeg(m3u8_url, output_file, referer)

    def _download_m3u8_ffmpeg(self, m3u8_url: str, output_file: Path, referer: str) -> bool:
        """用 ffmpeg 单线程下载 m3u8（备用方案）。"""
        output_file = output_file.with_suffix(".mp4")
        cmd = [
            _get_ffmpeg_path(), "-y", "-progress", "pipe:1", "-nostats",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "10",
            "-rw_timeout", "15000000",
            "-headers", f"User-Agent: {self.session.headers['User-Agent']}\r\nReferer: {referer}\r\n",
            "-i", m3u8_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            str(output_file),
        ]
        self.logger.info(f"ffmpeg 单线程下载 m3u8: {m3u8_url}")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            cols = shutil.get_terminal_size().columns
            last_time = ""
            total_bytes = 0
            last_print = 0.0
            prev_bytes = 0
            prev_ts = 0.0
            start_ts = time.monotonic()
            speed_str = ""
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time="):
                    raw = line.split("=", 1)[1]
                    if raw and not raw.startswith("N/A"):
                        last_time = raw.split(".")[0]
                elif line.startswith("total_size="):
                    val = line.split("=", 1)[1]
                    if val.isdigit():
                        total_bytes = int(val)
                now = time.monotonic()
                if last_time and now - last_print >= 1.0:
                    dt = now - prev_ts if prev_ts else 1.0
                    if dt > 0 and prev_ts:
                        speed = (total_bytes - prev_bytes) / dt
                        if speed >= 1024 * 1024:
                            speed_str = f"{speed / (1024 * 1024):.1f} MB/s"
                        else:
                            speed_str = f"{speed / 1024:.0f} KB/s"
                    prev_bytes = total_bytes
                    prev_ts = now
                    last_print = now
                    elapsed = int(now - start_ts)
                    elapsed_str = f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"
                    size_mb = total_bytes / (1024 * 1024)
                    status = f"\r  m3u8 下载中  视频 {last_time} | {size_mb:.1f} MB | 耗时 {elapsed_str} | 速度 {speed_str}"
                    print(f"{status:<{cols}}", end="", flush=True)
            proc.wait(timeout=3600)
            print()
            if proc.returncode == 0 and output_file.exists() and output_file.stat().st_size > 0:
                size_mb = output_file.stat().st_size / (1024 * 1024)
                self.logger.info(f"m3u8 转换完成: {output_file} ({size_mb:.1f} MB)")
                return True
            stderr = proc.stderr.read()
            self.logger.error(f"ffmpeg 失败 (code={proc.returncode}): {stderr[-500:]}")
            return False
        except FileNotFoundError:
            self.logger.error("ffmpeg 未安装，无法处理 m3u8。请运行: sudo apt install ffmpeg")
            return False
        except subprocess.TimeoutExpired:
            proc.kill()
            self.logger.error("ffmpeg 超时（1 小时），下载中止。")
            return False
        except Exception as exc:
            self.logger.error(f"ffmpeg 下载失败: {exc}")
            return False

    @staticmethod
    def _is_m3u8(url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith(".m3u8") or ".m3u8?" in url.lower()

    def _manual_download(self, url: str, output_path: str = "./downloads/") -> bool:
        """直链下载（仅回退）。检测到 m3u8 时自动用 ffmpeg 转 mp4。"""
        video_url = None
        file_path = None
        try:
            Path(output_path).mkdir(parents=True, exist_ok=True)
            video_info = self.extract_generic_video(url)
            if not video_info or not video_info.video_urls:
                self.logger.error("未找到可下载直链。")
                return False

            m3u8_urls = [u for u in video_info.video_urls if self._is_m3u8(u)]
            mp4_urls = [u for u in video_info.video_urls if not self._is_m3u8(u)]

            safe_title = (video_info.title or "video").replace("/", "_").replace("\\", "_").strip()

            if m3u8_urls:
                video_url = m3u8_urls[0]
                file_path = Path(output_path) / f"{safe_title[:120]}.mp4"
                return self._download_m3u8(video_url, file_path, referer=self.referer or url)

            video_url = mp4_urls[0] if mp4_urls else video_info.video_urls[0]
            ext = "mp4"
            maybe_name = Path(urlparse(video_url).path).name
            if "." in maybe_name:
                ext = maybe_name.split(".")[-1][:8]
            file_path = Path(output_path) / f"{safe_title[:120]}.{ext}"
            self.logger.info(f"直链下载: {video_url}")

            headers = {"Referer": self.referer or url, "User-Agent": self.session.headers["User-Agent"]}
            with self.session.get(video_url, stream=True, timeout=self.timeout, headers=headers) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                chunk_size = 1024 * 512
                if HAS_TQDM and total > 0:
                    with open(file_path, "wb") as fp, tqdm(
                        total=total, unit="B", unit_scale=True, unit_divisor=1024,
                        desc=file_path.name[:40], ncols=shutil.get_terminal_size().columns,
                    ) as bar:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if chunk:
                                fp.write(chunk)
                                bar.update(len(chunk))
                else:
                    downloaded = 0
                    with open(file_path, "wb") as fp:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if chunk:
                                fp.write(chunk)
                                downloaded += len(chunk)
                                mb = downloaded / (1024 * 1024)
                                print(f"\r已下载: {mb:.1f} MB", end="", flush=True)
                    print()
            self.logger.info(f"直链下载完成: {file_path}")
            return True
        except Exception as exc:
            self.logger.error(f"直链下载失败: {exc}")
            if video_url and file_path:
                return self._download_with_curl(video_url=video_url, output_path=file_path, referer=self.referer or url)
            return False

    def _download_with_curl(self, video_url: str, output_path: Path, referer: str) -> bool:
        """使用 curl 备用下载（带进度条）"""
        try:
            cmd = [
                "curl",
                "-L", "-#",
                "--retry", "3",
                "-H", f"User-Agent: {self.session.headers['User-Agent']}",
                "-H", f"Referer: {referer}",
                "-o", str(output_path),
                video_url,
            ]
            subprocess.run(cmd, check=True)
            self.logger.info(f"curl 下载完成: {output_path}")
            return True
        except Exception as exc:
            self.logger.error(f"curl 下载失败: {exc}")
            return False

    def download_video(self, url: str, output_path: str = "./downloads/") -> bool:
        """下载视频文件。yt-dlp 失败时自动回退到通用直链下载。"""
        if not HAS_YTDLP:
            self.logger.info("yt-dlp 不可用，直接使用通用直链下载。")
            return self._manual_download(url, output_path)

        try:
            ydl_opts = self._build_ydl_opts(download=True, output_path=output_path)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                code = ydl.download([url])
            if code == 0:
                self.logger.info(f"yt-dlp 下载成功: {url}")
                return True
            self.logger.warning(f"yt-dlp 返回非零状态，回退通用直链下载: {url}")
        except Exception as exc:
            self.logger.warning(f"yt-dlp 下载失败({exc})，回退通用直链下载。")

        return self._manual_download(url, output_path)

    def _list_formats_fallback(self, url: str) -> bool:
        """yt-dlp 不可用或失败时，用通用提取展示候选直链。"""
        self.logger.info(f"回退到通用直链提取: {url}")
        info = self.extract_generic_video(url)
        if not info or not info.video_urls:
            print("未找到可用视频链接。")
            return False
        print(f"\n提取到的候选直链 ({len(info.video_urls)}):")
        for idx, item in enumerate(info.video_urls, start=1):
            print(f"  {idx:02d}. {item}")
        return True

    def list_formats(self, url: str) -> bool:
        """列出视频可用格式"""
        if not HAS_YTDLP:
            self.logger.warning("yt-dlp 不可用，回退通用提取。")
            return self._list_formats_fallback(url)
        try:
            opts = self._build_ydl_opts(download=False)
            opts["listformats"] = True
            opts["quiet"] = False
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=False)
            return True
        except Exception as exc:
            self.logger.warning(f"yt-dlp 格式列表失败({exc})，回退通用提取。")
            return self._list_formats_fallback(url)

    @staticmethod
    def _infer_resource_links(soup: "BeautifulSoup", base_url: str) -> List[str]:
        """从页面中推断资源页链接：分析所有 <a> 标签，按路径深度和特征自动过滤。"""
        base_parsed = urlparse(base_url)
        base_domain = base_parsed.netloc.lower()
        base_path = base_parsed.path.rstrip("/")

        noise_patterns = re.compile(
            r"(?:login|signup|register|about|contact|terms|privacy|faq|help|search"
            r"|tag|category|categories|sort|lang|locale|#|javascript:|mailto:)",
            re.IGNORECASE,
        )
        media_ext = re.compile(r"\.(mp4|m3u8|webm|avi|mkv|flv|mov|m4v|mp3|wav|ogg)(\?|$)", re.IGNORECASE)

        candidates: List[str] = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            if not href or href == "#":
                continue
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)

            if parsed.netloc.lower() != base_domain:
                continue
            if noise_patterns.search(full_url):
                continue

            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if clean_url in seen or clean_url.rstrip("/") == base_url.rstrip("/"):
                continue
            seen.add(clean_url)

            path = parsed.path.rstrip("/")
            if not path or path == base_path:
                continue

            depth = len([seg for seg in path.split("/") if seg])
            if depth < 2:
                continue

            if media_ext.search(path):
                candidates.append(full_url)
                continue

            is_static = re.search(r"\.(css|js|png|jpg|jpeg|gif|svg|ico|woff|ttf|pdf|zip|rar)(\?|$)", path, re.IGNORECASE)
            if is_static:
                continue

            candidates.append(full_url)

        return candidates

    def discover_videos(
        self,
        url: str,
        limit: int = 10,
        page_limit: int = 1,
        url_pattern: Optional[str] = None,
        css_selector: Optional[str] = None,
        same_domain: bool = True,
    ) -> List[str]:
        """从列表页/首页批量发现资源链接。

        Args:
            url: 起始页 URL
            limit: 最多发现多少个链接
            page_limit: 最大翻页数
            url_pattern: 自定义正则，仅保留匹配的链接（如 r'/videos/\\w+')
            css_selector: CSS 选择器，限定在某个区域内提取链接（如 'div.video-list a')
            same_domain: 是否只保留同域名链接
        """
        discovered_urls: List[str] = []
        current_url = url
        base_domain = urlparse(url).netloc.lower()
        user_re = re.compile(url_pattern) if url_pattern else None
        self.logger.info(f"开始发现资源链接: {url}")

        for page in range(1, page_limit + 1):
            if len(discovered_urls) >= limit:
                break
            try:
                response = self._extract_with_requests(current_url)
                if not HAS_BS4:
                    self.logger.warning("BeautifulSoup 不可用，跳过 discover。")
                    break
                soup = BeautifulSoup(response.content, "html.parser")

                if css_selector:
                    anchors = soup.select(css_selector)
                    raw_links = []
                    for el in anchors:
                        if el.name == "a" and el.get("href"):
                            raw_links.append(urljoin(current_url, el["href"]))
                        else:
                            for a in el.find_all("a", href=True):
                                raw_links.append(urljoin(current_url, a["href"]))
                elif url_pattern:
                    raw_links = []
                    for a in soup.find_all("a", href=True):
                        full = urljoin(current_url, a["href"])
                        raw_links.append(full)
                else:
                    raw_links = self._infer_resource_links(soup, current_url)

                seen = set(discovered_urls)
                for link in raw_links:
                    if len(discovered_urls) >= limit:
                        break
                    parsed = urlparse(link)
                    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    if clean in seen:
                        continue
                    if same_domain and parsed.netloc.lower() != base_domain:
                        continue
                    if user_re and not user_re.search(link):
                        continue
                    seen.add(clean)
                    discovered_urls.append(link)
                    self.logger.info(f"发现资源页: {link}")

                if page < page_limit and len(discovered_urls) < limit:
                    next_link = soup.find("a", string=re.compile(r"(下一页|next|>|»)", flags=re.IGNORECASE))
                    if not next_link:
                        next_link = soup.find("a", class_=re.compile(r"next", re.IGNORECASE))
                    if not next_link:
                        next_link = soup.find("a", rel="next")
                    if next_link and next_link.get("href"):
                        current_url = urljoin(current_url, next_link["href"])
                        self.logger.info(f"翻页: {current_url}")
                    else:
                        self.logger.info("未找到下一页链接，停止翻页。")
                        break
            except Exception as exc:
                self.logger.error(f"页面发现失败: {exc}")
                break

        self.logger.info(f"共发现 {len(discovered_urls)} 个资源链接")
        return discovered_urls[:limit]

    def discover_and_download(
        self,
        url: str,
        limit: int = 10,
        page_limit: int = 1,
        url_pattern: Optional[str] = None,
        css_selector: Optional[str] = None,
        output_path: str = "./downloads/",
        delay: float = 2.0,
    ) -> Dict[str, bool]:
        """从列表页发现资源链接并批量下载。返回 {url: 是否成功}。"""
        urls = self.discover_videos(
            url, limit=limit, page_limit=page_limit,
            url_pattern=url_pattern, css_selector=css_selector,
        )
        if not urls:
            self.logger.warning("未发现任何资源链接。")
            return {}

        self.logger.info(f"开始批量下载 {len(urls)} 个资源...")
        results = {}
        for idx, u in enumerate(urls, 1):
            self.logger.info(f"下载进度 {idx}/{len(urls)}: {u}")
            results[u] = self.download_video(u, output_path)
            if idx < len(urls):
                time.sleep(delay)

        ok = sum(1 for v in results.values() if v)
        self.logger.info(f"批量下载完成: {ok}/{len(urls)} 成功")
        return results

    def save_to_json(self, filename: str = "video_data.json"):
        """保存视频信息为 JSON"""
        data = [asdict(video) for video in self.scraped_videos]
        with open(filename, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
        self.logger.info(f"视频数据已保存到: {filename}")


def _read_urls_from_file(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as fp:
        return [line.strip() for line in fp if line.strip() and not line.strip().startswith("#")]


def main():
    parser = argparse.ArgumentParser(description="Video Scraper - 公开非加密视频网站下载工具")
    parser.add_argument("urls", nargs="*", help="视频 URL 列表")
    parser.add_argument("--input-file", "-f", help="包含视频 URL 的文本文件")
    parser.add_argument("--discover", action="store_true", help="自动发现视频链接")
    parser.add_argument("--limit", type=int, default=10, help="发现视频数量限制")
    parser.add_argument("--page-limit", type=int, default=1, help="discover 最大翻页数")
    parser.add_argument("--url-pattern", help="discover 时自定义 URL 正则过滤（如 '/videos/\\w+'）")
    parser.add_argument("--css-selector", help="discover 时限定提取区域的 CSS 选择器（如 'div.video-list a'）")
    parser.add_argument("--discover-download", action="store_true", help="发现并直接下载")
    parser.add_argument("--delay", type=float, default=2.0, help="批量下载间隔（秒）")
    parser.add_argument("--download", action="store_true", help="下载视频")
    parser.add_argument("--convert-m3u8", action="store_true", help="将 URL 视为 m3u8 流，用 ffmpeg 直接转 mp4")
    parser.add_argument("--list-formats", action="store_true", help="列出可用格式")
    parser.add_argument("--quality", default="best", help="下载质量，如 best / 720p / worst")
    parser.add_argument(
        "--browser",
        choices=["chrome", "firefox", "safari", "edge", "chromium"],
        help="从浏览器读取登录态 cookies（可选）",
    )
    parser.add_argument("--cookies-file", default="cookies.txt", help="cookies 文件（Netscape 格式）")
    parser.add_argument("--proxy", help="代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--referer", help="自定义 Referer")
    parser.add_argument("--timeout", type=int, default=30, help="请求超时（秒）")
    parser.add_argument("--retries", type=int, default=3, help="请求重试次数")
    parser.add_argument("--audio-only", action="store_true", help="仅下载音频（mp3）")
    parser.add_argument("--concurrent-fragments", type=int, default=4, help="分片并发下载数")
    parser.add_argument("--output", default="video_data.json", help="元数据输出 JSON 文件")
    parser.add_argument("--download-path", default="./downloads/", help="下载路径")

    args = parser.parse_args()
    scraper = VideoScraper(
        quality=args.quality,
        browser=args.browser,
        cookies_file=args.cookies_file,
        timeout=args.timeout,
        retries=args.retries,
        proxy=args.proxy,
        referer=args.referer,
        audio_only=args.audio_only,
        concurrent_fragments=args.concurrent_fragments,
    )

    target_urls = list(args.urls or [])
    if args.input_file:
        try:
            file_urls = _read_urls_from_file(args.input_file)
            print(f"从文件读取 URL 数量: {len(file_urls)}")
            target_urls.extend(file_urls)
        except Exception as exc:
            print(f"读取输入文件失败: {exc}")
            return

    if args.discover_download:
        seed = target_urls[0] if target_urls else ""
        if not seed:
            print("请提供起始页 URL。")
            return
        print(f"发现并下载，起始页: {seed}")
        results = scraper.discover_and_download(
            seed, limit=args.limit, page_limit=args.page_limit,
            url_pattern=args.url_pattern, css_selector=args.css_selector,
            output_path=args.download_path, delay=args.delay,
        )
        ok = sum(1 for v in results.values() if v)
        print(f"完成: {ok}/{len(results)} 成功")
        return

    if args.discover:
        seed = target_urls[0] if target_urls else ""
        if not seed:
            print("请提供起始页 URL。")
            return
        print(f"开始发现资源链接，起始页: {seed}")
        discovered = scraper.discover_videos(
            seed, limit=args.limit, page_limit=args.page_limit,
            url_pattern=args.url_pattern, css_selector=args.css_selector,
        )
        print(f"发现资源链接数量: {len(discovered)}")
        for idx, u in enumerate(discovered, 1):
            print(f"  {idx:02d}. {u}")
        target_urls.extend(discovered)

    if args.convert_m3u8:
        if not target_urls:
            print("请提供 m3u8 URL。")
            return
        Path(args.download_path).mkdir(parents=True, exist_ok=True)
        ok = 0
        for idx, m3u8_url in enumerate(target_urls, 1):
            out_file = Path(args.download_path) / f"video_{idx:03d}.mp4"
            print(f"[{idx}/{len(target_urls)}] 转换: {m3u8_url}")
            if scraper._download_m3u8(m3u8_url, out_file, referer=args.referer or m3u8_url):
                ok += 1
        print(f"转换完成: {ok}/{len(target_urls)} 成功")
        return

    target_urls = sorted(set(target_urls))
    if not target_urls:
        print("未提供 URL。请传入 URL 参数、--input-file 或 --discover。")
        parser.print_help()
        return

    if args.list_formats:
        for url in target_urls:
            print(f"\n格式列表: {url}")
            scraper.list_formats(url)
        return

    print(f"开始提取 {len(target_urls)} 个 URL...")
    results = scraper.scrape_videos(target_urls)
    if results:
        print(f"提取成功: {len(results)}")
        scraper.save_to_json(args.output)
    else:
        print("未提取到有效视频信息。")

    if args.download:
        print("开始下载...")
        ok = 0
        for url in target_urls:
            if scraper.download_video(url, args.download_path):
                ok += 1
        print(f"下载完成: {ok}/{len(target_urls)} 成功")


if __name__ == "__main__":
    main()