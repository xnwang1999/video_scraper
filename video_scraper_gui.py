#!/usr/bin/env python3
"""Video Scraper GUI - 基于 customtkinter 的图形界面"""

import io
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from video_scraper import VideoScraper, StopRequested, _read_urls_from_file, APP_VERSION, _default_download_dir

# ── 色彩系统（light, dark）─────────────────────────────────────
# customtkinter 接受 (light_value, dark_value) 元组，自动跟随主题切换
C = {
    "bg":            ("#f0f2f5", "#1a1a2e"),
    "card":          ("#ffffff", "#16213e"),
    "input":         ("#f5f7fa", "#0d1b36"),
    "border":        ("#d0d5dd", "#2a3a5e"),
    "text1":         ("#1a1a2e", "#e8eaed"),
    "text2":         ("#555555", "#9aa0a6"),
    "tag_bg":        ("#e0e7ef", "#1e3a5f"),
    "tag_hover":     ("#c8d1dc", "#2a3a5e"),
    "ghost_hover":   ("#e8ecf0", "#2a3a5e"),
    "accent":        "#0f7dff",
    "accent_hover":  "#0a5cbf",
    "green":         "#00c853",
    "green_hover":   "#009940",
    "purple":        "#7c4dff",
    "purple_hover":  "#5c35cc",
    "red":           "#ff3d57",
    "red_hover":     "#cc2e44",
    "orange":        "#ff9100",
}


class QueueHandler(logging.Handler):
    """将日志消息发送到队列，由主线程消费并显示在 GUI 中。"""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put_nowait(self.format(record))
        except queue.Full:
            pass


class StdoutRedirector(io.TextIOBase):
    """将 stdout/stderr 写入重定向到队列。"""

    def __init__(self, log_queue: queue.Queue):
        self.log_queue = log_queue

    def write(self, text):
        if text and text.strip():
            try:
                self.log_queue.put_nowait(text.rstrip())
            except queue.Full:
                pass
        return len(text) if text else 0

    def flush(self):
        pass


class APIHandler(BaseHTTPRequestHandler):
    """处理来自浏览器扩展的 HTTP 请求。"""
    gui: "VideoScraperGUI" = None

    def log_message(self, format, *args):
        pass

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/health":
            self._json_response(200, {"status": "ok"})
        elif self.path == "/api/show":
            gui = APIHandler.gui
            if gui:
                gui.after(0, lambda: (gui.deiconify(), gui.lift(), gui.focus_force()))
                self._json_response(200, {"status": "ok"})
            else:
                self._json_response(500, {"error": "GUI not ready"})
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/task":
            self._json_response(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._json_response(400, {"error": "invalid JSON"})
            return

        url = body.get("url", "").strip()
        action = body.get("action", "download")
        quality = body.get("quality", "best")
        cookies_text = body.get("cookies", "")

        if not url:
            self._json_response(400, {"error": "url is required"})
            return

        gui = APIHandler.gui
        if gui is None:
            self._json_response(500, {"error": "GUI not ready"})
            return

        gui.after(0, lambda: gui._handle_extension_task(url, action, quality, cookies_text))
        self._json_response(200, {"message": f"已接收，正在{('下载' if action == 'download' else '提取')}: {url}"})


class VideoScraperGUI(ctk.CTk):
    QUALITIES = ["best", "1080p", "720p", "480p", "360p", "worst"]
    BROWSERS = ["无", "chrome", "firefox", "edge", "chromium"]
    API_PORT = 9527

    def __init__(self):
        super().__init__()
        self.title("Video Scraper")
        self.geometry("1000x800")
        self.minsize(860, 650)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=C["bg"])

        self._log_queue: queue.Queue = queue.Queue(maxsize=5000)
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._title_font = ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
        self._section_font = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        self._body_font = ctk.CTkFont(family="Segoe UI", size=12)
        self._small_font = ctk.CTkFont(family="Segoe UI", size=11)
        self._mono_font = ctk.CTkFont(family="Consolas", size=11)

        self._build_ui()
        self._setup_logging()
        self._poll_log_queue()
        self._start_api_server()

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._build_header(row=0)
        self._build_url_section(row=1)
        self._build_settings_section(row=2)
        self._build_action_buttons(row=3)
        self._build_log_section(row=4)
        self._build_status_bar(row=5)

    def _build_header(self, row: int):
        frame = ctk.CTkFrame(self, fg_color="transparent", height=50)
        frame.grid(row=row, column=0, padx=16, pady=(12, 0), sticky="ew")
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame, text="Video Scraper", font=self._title_font,
            text_color=C["accent"],
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            frame, text=f"v{APP_VERSION}", font=self._small_font,
            text_color=C["text2"],
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.theme_btn = ctk.CTkButton(
            frame, text="Light", width=60, height=28,
            font=self._small_font, corner_radius=14,
            fg_color=C["tag_bg"], hover_color=C["tag_hover"],
            text_color=C["text1"],
            command=self._toggle_theme,
        )
        self.theme_btn.grid(row=0, column=2, sticky="e")
        self._dark_mode = True

    def _build_url_section(self, row: int):
        frame = self._card(self, row=row, pady=(10, 4))
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="URL", font=self._section_font,
            text_color=C["text1"],
        ).grid(row=0, column=0, sticky="w")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")

        self._tag_btn(btn_frame, "导入文件", self._import_urls).grid(row=0, column=0, padx=(0, 6))
        self._ghost_btn(btn_frame, "清空", self._clear_urls).grid(row=0, column=1)

        self.url_textbox = ctk.CTkTextbox(
            frame, height=90, wrap="none", corner_radius=8,
            font=self._body_font, fg_color=C["input"],
            border_width=1, border_color=C["border"],
            text_color=C["text1"],
        )
        self.url_textbox.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="ew")

    def _build_settings_section(self, row: int):
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.grid(row=row, column=0, padx=16, pady=4, sticky="ew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)

        self._build_download_settings(outer, col=0)
        self._build_network_settings(outer, col=1)

    def _build_download_settings(self, parent, col: int):
        card = ctk.CTkFrame(
            parent, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"],
        )
        card.grid(row=0, column=col, padx=(0, 4) if col == 0 else (4, 0), pady=0, sticky="nsew")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text="下载设置", font=self._section_font,
            text_color=C["text1"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 8))

        r = 1
        self._label(card, "画质", r, 0)
        self.quality_var = ctk.StringVar(value="best")
        self.quality_combo = self._combo(card, self.QUALITIES, self.quality_var)
        self.quality_combo.grid(row=r, column=1, sticky="w", padx=6, pady=4)
        self._small_btn(card, "获取", self._on_fetch_qualities).grid(row=r, column=2, padx=(0, 14), pady=4)

        r += 1
        self._label(card, "下载路径", r, 0)
        self.download_path_var = ctk.StringVar(value=str(_default_download_dir()))
        self._entry(card, self.download_path_var).grid(row=r, column=1, sticky="ew", padx=6, pady=4)
        self._small_btn(card, "浏览", self._browse_download_path).grid(row=r, column=2, padx=(0, 4), pady=4)
        self._small_btn(card, "打开", self._open_download_dir).grid(row=r, column=3, padx=(0, 14), pady=4)

        r += 1
        self.audio_only_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            card, text="仅下载音频 (MP3)", variable=self.audio_only_var,
            font=self._body_font, corner_radius=4, border_width=2,
            fg_color=C["accent"], hover_color=C["accent_hover"],
            border_color=C["border"], text_color=C["text1"],
        ).grid(row=r, column=0, columnspan=2, sticky="w", padx=14, pady=4)

        r += 1
        num_frame = ctk.CTkFrame(card, fg_color="transparent")
        num_frame.grid(row=r, column=0, columnspan=3, sticky="ew", padx=14, pady=(4, 12))

        ctk.CTkLabel(num_frame, text="并发分片", font=self._body_font, text_color=C["text2"]).pack(side="left")
        self.fragments_var = ctk.StringVar(value="4")
        self._small_entry(num_frame, self.fragments_var, 50).pack(side="left", padx=(6, 16))

        ctk.CTkLabel(num_frame, text="间隔(秒)", font=self._body_font, text_color=C["text2"]).pack(side="left")
        self.delay_var = ctk.StringVar(value="2.0")
        self._small_entry(num_frame, self.delay_var, 50).pack(side="left", padx=(6, 0))

    def _build_network_settings(self, parent, col: int):
        card = ctk.CTkFrame(
            parent, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"],
        )
        card.grid(row=0, column=col, padx=(0, 4) if col == 0 else (4, 0), pady=0, sticky="nsew")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text="网络设置", font=self._section_font,
            text_color=C["text1"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 8))

        r = 1
        self._label(card, "Cookies 文件", r, 0)
        self.cookies_var = ctk.StringVar(value="cookies.txt")
        self._entry(card, self.cookies_var).grid(row=r, column=1, sticky="ew", padx=6, pady=4)
        self._small_btn(card, "浏览", self._browse_cookies).grid(row=r, column=2, padx=(0, 14), pady=4)

        r += 1
        self._label(card, "浏览器 Cookies", r, 0)
        self.browser_var = ctk.StringVar(value="无")
        self._combo(card, self.BROWSERS, self.browser_var).grid(row=r, column=1, sticky="w", padx=6, pady=4)

        r += 1
        self._label(card, "代理地址", r, 0)
        self.proxy_var = ctk.StringVar(value="")
        self._entry(card, self.proxy_var, placeholder="http://127.0.0.1:7890").grid(
            row=r, column=1, columnspan=2, sticky="ew", padx=(6, 14), pady=4
        )

        r += 1
        self._label(card, "Referer", r, 0)
        self.referer_var = ctk.StringVar(value="")
        self._entry(card, self.referer_var).grid(
            row=r, column=1, columnspan=2, sticky="ew", padx=(6, 14), pady=4
        )

        r += 1
        num_frame = ctk.CTkFrame(card, fg_color="transparent")
        num_frame.grid(row=r, column=0, columnspan=3, sticky="ew", padx=14, pady=(4, 12))

        ctk.CTkLabel(num_frame, text="超时(秒)", font=self._body_font, text_color=C["text2"]).pack(side="left")
        self.timeout_var = ctk.StringVar(value="30")
        self._small_entry(num_frame, self.timeout_var, 50).pack(side="left", padx=(6, 16))

        ctk.CTkLabel(num_frame, text="重试次数", font=self._body_font, text_color=C["text2"]).pack(side="left")
        self.retries_var = ctk.StringVar(value="3")
        self._small_entry(num_frame, self.retries_var, 50).pack(side="left", padx=(6, 0))

    def _build_action_buttons(self, row: int):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=0, padx=16, pady=6, sticky="ew")

        btn_configs = [
            ("提取信息", C["green"], C["green_hover"], self._on_extract),
            ("下载视频", C["accent"], C["accent_hover"], self._on_download),
            ("查看格式", C["purple"], C["purple_hover"], self._on_list_formats),
            ("停止", C["red"], C["red_hover"], self._on_stop),
        ]
        for text, fg, hover, cmd in btn_configs:
            ctk.CTkButton(
                frame, text=text, font=self._body_font,
                height=38, corner_radius=10,
                fg_color=fg, hover_color=hover,
                text_color="white",
                command=cmd,
            ).pack(side="left", padx=4, expand=True, fill="x")

    def _build_log_section(self, row: int):
        frame = self._card(self, row=row, pady=4, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="日志", font=self._section_font,
            text_color=C["text1"],
        ).grid(row=0, column=0, sticky="w")

        self._ghost_btn(header, "清空", self._clear_log).grid(row=0, column=1, sticky="e")

        self.log_textbox = ctk.CTkTextbox(
            frame, wrap="word", state="disabled",
            font=self._mono_font, corner_radius=8,
            fg_color=C["input"], text_color=C["text1"],
            border_width=0,
        )
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(2, 10), sticky="nsew")

    def _build_status_bar(self, row: int):
        frame = ctk.CTkFrame(
            self, fg_color=C["card"], corner_radius=10,
            height=36, border_width=1, border_color=C["border"],
        )
        frame.grid(row=row, column=0, padx=16, pady=(2, 12), sticky="ew")
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=2)

        self.status_dot = ctk.CTkLabel(
            frame, text="", width=10, height=10, corner_radius=5,
            fg_color=C["green"],
        )
        self.status_dot.grid(row=0, column=0, padx=(14, 6), pady=8)

        self.status_label = ctk.CTkLabel(
            frame, text="就绪", anchor="w",
            font=self._small_font, text_color=C["text2"],
        )
        self.status_label.grid(row=0, column=1, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(
            frame, height=6, corner_radius=3,
            fg_color=C["input"], progress_color=C["accent"],
        )
        self.progress_bar.grid(row=0, column=2, padx=(10, 14), pady=8, sticky="ew")
        self.progress_bar.set(0)

    # ── 组件工厂方法 ──────────────────────────────────────────

    def _card(self, parent, row: int, pady=4, sticky="ew"):
        frame = ctk.CTkFrame(
            parent, fg_color=C["card"], corner_radius=12,
            border_width=1, border_color=C["border"],
        )
        frame.grid(row=row, column=0, padx=16, pady=pady, sticky=sticky)
        return frame

    def _label(self, parent, text: str, row: int, col: int):
        ctk.CTkLabel(
            parent, text=text, font=self._body_font,
            text_color=C["text2"],
        ).grid(row=row, column=col, sticky="w", padx=14, pady=4)

    def _entry(self, parent, var, placeholder: str = ""):
        return ctk.CTkEntry(
            parent, textvariable=var, height=30, corner_radius=8,
            font=self._body_font, fg_color=C["input"],
            border_color=C["border"], text_color=C["text1"],
            placeholder_text=placeholder,
        )

    def _small_entry(self, parent, var, width: int):
        return ctk.CTkEntry(
            parent, textvariable=var, width=width, height=28,
            corner_radius=6, font=self._body_font,
            fg_color=C["input"], border_color=C["border"],
            text_color=C["text1"],
        )

    def _combo(self, parent, values, var):
        return ctk.CTkComboBox(
            parent, values=values, variable=var,
            width=130, height=30, corner_radius=8, font=self._body_font,
            fg_color=C["input"], border_color=C["border"],
            text_color=C["text1"],
            button_color=C["accent"], button_hover_color=C["accent_hover"],
            dropdown_fg_color=C["card"], dropdown_text_color=C["text1"],
        )

    def _small_btn(self, parent, text: str, cmd):
        return ctk.CTkButton(
            parent, text=text, width=52, height=28,
            font=self._small_font, corner_radius=8,
            fg_color=C["tag_bg"], hover_color=C["tag_hover"],
            text_color=C["text1"],
            command=cmd,
        )

    def _tag_btn(self, parent, text: str, cmd):
        return ctk.CTkButton(
            parent, text=text, width=80, height=28,
            font=self._small_font, corner_radius=8,
            fg_color=C["tag_bg"], hover_color=C["tag_hover"],
            text_color=C["text1"],
            command=cmd,
        )

    def _ghost_btn(self, parent, text: str, cmd):
        return ctk.CTkButton(
            parent, text=text, width=52, height=28,
            font=self._small_font, corner_radius=8,
            fg_color="transparent", hover_color=C["ghost_hover"],
            border_width=1, border_color=C["border"],
            text_color=C["text2"],
            command=cmd,
        )

    # ── 日志系统 ──────────────────────────────────────────────

    def _setup_logging(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)

        handler = QueueHandler(self._log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root_logger.addHandler(handler)

    def _poll_log_queue(self):
        batch = []
        try:
            while True:
                batch.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass

        if batch:
            self.log_textbox.configure(state="normal")
            for msg in batch:
                self.log_textbox.insert("end", msg + "\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")

        self.after(100, self._poll_log_queue)

    def _log(self, msg: str):
        self._log_queue.put_nowait(msg)

    # ── 工具方法 ──────────────────────────────────────────────

    def _toggle_theme(self):
        if self._dark_mode:
            ctk.set_appearance_mode("light")
            self.theme_btn.configure(text="Dark")
        else:
            ctk.set_appearance_mode("dark")
            self.theme_btn.configure(text="Light")
        self._dark_mode = not self._dark_mode

    def _get_urls(self) -> list[str]:
        text = self.url_textbox.get("1.0", "end").strip()
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]

    def _build_scraper(self) -> VideoScraper:
        browser = self.browser_var.get()
        if browser == "无":
            browser = None

        proxy = self.proxy_var.get().strip() or None
        referer = self.referer_var.get().strip() or None

        return VideoScraper(
            quality=self.quality_var.get(),
            browser=browser,
            cookies_file=self.cookies_var.get(),
            timeout=int(self.timeout_var.get() or 30),
            retries=int(self.retries_var.get() or 3),
            proxy=proxy,
            referer=referer,
            audio_only=self.audio_only_var.get(),
            concurrent_fragments=int(self.fragments_var.get() or 4),
            stop_event=self._stop_event,
        )

    def _set_busy(self, status: str):
        self.status_label.configure(text=status)
        self.status_dot.configure(fg_color=C["orange"])
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

    def _set_idle(self, status: str = "就绪"):
        self.status_label.configure(text=status)
        self.status_dot.configure(fg_color=C["green"])
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        self._worker_thread = None

    def _is_busy(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def _run_in_thread(self, target, status: str):
        if self._is_busy():
            self._log("有任务正在执行，请等待或点击停止。")
            return
        self._stop_event.clear()
        self._set_busy(status)
        self._worker_thread = threading.Thread(target=target, daemon=True)
        self._worker_thread.start()

    # ── 按钮回调 ──────────────────────────────────────────────

    def _on_fetch_qualities(self):
        urls = self._get_urls()
        if not urls:
            self._log("请先输入 URL 再获取可用画质。")
            return
        self._run_in_thread(lambda: self._do_fetch_qualities(urls[0]), "获取画质中...")

    def _do_fetch_qualities(self, url: str):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        redirector = StdoutRedirector(self._log_queue)
        sys.stdout = redirector
        sys.stderr = redirector
        try:
            scraper = self._build_scraper()
            self._log(f"正在获取可用画质: {url}")

            info = scraper.extract_with_ytdlp(url)
            if info and info.formats:
                resolutions = set()
                for fmt in info.formats:
                    res = fmt.get("resolution", "")
                    if "x" in res:
                        try:
                            h = int(res.split("x")[-1])
                            if h > 0:
                                resolutions.add(h)
                        except ValueError:
                            pass
                if resolutions:
                    sorted_res = sorted(resolutions, reverse=True)
                    values = ["best"] + [f"{h}p" for h in sorted_res] + ["worst"]
                    self._log(f"可用画质: {', '.join(values)}")
                    self.after(0, lambda: self._update_quality_options(values))
                    return
                    
            import yt_dlp
            opts = scraper._build_ydl_opts(download=False)
            opts["quiet"] = True
            opts["no_warnings"] = True
            with yt_dlp.YoutubeDL(opts) as ydl:
                raw_info = ydl.extract_info(url, download=False)

            if not raw_info or not raw_info.get("formats"):
                self._log("未获取到格式信息，保持默认选项。")
                return

            resolutions = set()
            for fmt in raw_info["formats"]:
                h = fmt.get("height")
                if h and isinstance(h, int) and h > 0:
                    resolutions.add(h)

            if not resolutions:
                self._log("未发现有效分辨率，保持默认选项。")
                return

            sorted_res = sorted(resolutions, reverse=True)
            values = ["best"] + [f"{h}p" for h in sorted_res] + ["worst"]
            self._log(f"可用画质: {', '.join(values)}")

            self.after(0, lambda: self._update_quality_options(values))
        except Exception as exc:
            self._log(f"获取画质失败: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            self.after(0, lambda: self._set_idle("获取完成"))

    def _update_quality_options(self, values: list[str]):
        self.quality_combo.configure(values=values)
        if self.quality_var.get() not in values:
            self.quality_var.set(values[0])

    def _import_urls(self):
        filepath = filedialog.askopenfilename(
            title="选择 URL 文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not filepath:
            return
        try:
            urls = _read_urls_from_file(filepath)
            if urls:
                existing = self.url_textbox.get("1.0", "end").strip()
                if existing:
                    self.url_textbox.insert("end", "\n")
                self.url_textbox.insert("end", "\n".join(urls))
                self._log(f"已导入 {len(urls)} 个 URL")
        except Exception as exc:
            self._log(f"导入文件失败: {exc}")

    def _clear_urls(self):
        self.url_textbox.delete("1.0", "end")

    def _clear_log(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _browse_download_path(self):
        path = filedialog.askdirectory(title="选择下载目录")
        if path:
            self.download_path_var.set(path)

    def _open_download_dir(self):
        path = self.download_path_var.get() or str(_default_download_dir())
        target = Path(path).resolve()
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])

    def _browse_cookies(self):
        filepath = filedialog.askopenfilename(
            title="选择 Cookies 文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if filepath:
            self.cookies_var.set(filepath)

    def _on_stop(self):
        if self._is_busy():
            self._stop_event.set()
            self._log("正在停止当前任务...")
        else:
            self._log("当前没有正在执行的任务。")

    # ── 核心操作 ──────────────────────────────────────────────

    def _on_extract(self):
        urls = self._get_urls()
        if not urls:
            self._log("请输入至少一个 URL。")
            return
        self._run_in_thread(lambda: self._do_extract(urls), "提取中...")

    def _do_extract(self, urls: list[str]):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        redirector = StdoutRedirector(self._log_queue)
        sys.stdout = redirector
        sys.stderr = redirector
        try:
            scraper = self._build_scraper()
            self._log(f"开始提取 {len(urls)} 个 URL 的视频信息...")
            for i, url in enumerate(urls, 1):
                if self._stop_event.is_set():
                    self._log("任务已停止。")
                    break
                self._log(f"[{i}/{len(urls)}] {url}")
                info = scraper.extract_with_ytdlp(url)
                if info is None:
                    info = scraper.extract_generic_video(url)
                if info:
                    self._log(f"  标题: {info.title}")
                    self._log(f"  平台: {info.platform}")
                    self._log(f"  时长: {info.duration}")
                    self._log(f"  上传者: {info.uploader}")
                    if info.video_urls:
                        self._log(f"  视频流: {len(info.video_urls)} 个")
                else:
                    self._log(f"  未能提取到视频信息。")
            self._log("提取完成。")
        except StopRequested:
            self._log("任务已停止。")
        except Exception as exc:
            self._log(f"提取出错: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            self.after(0, lambda: self._set_idle("提取完成"))

    def _on_download(self):
        urls = self._get_urls()
        if not urls:
            self._log("请输入至少一个 URL。")
            return
        self._run_in_thread(lambda: self._do_download(urls), "下载中...")

    def _do_download(self, urls: list[str]):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        redirector = StdoutRedirector(self._log_queue)
        sys.stdout = redirector
        sys.stderr = redirector
        try:
            scraper = self._build_scraper()
            output_path = self.download_path_var.get() or "./downloads/"
            delay = float(self.delay_var.get() or 2.0)
            ok = 0
            self._log(f"开始下载 {len(urls)} 个视频...")
            for i, url in enumerate(urls, 1):
                if self._stop_event.is_set():
                    self._log("任务已停止。")
                    break
                self._log(f"[{i}/{len(urls)}] 下载: {url}")
                if scraper.download_video(url, output_path):
                    ok += 1
                    self._log(f"  下载成功。")
                else:
                    self._log(f"  下载失败。")
                if i < len(urls) and not self._stop_event.is_set():
                    if self._stop_event.wait(delay):
                        break
            self._log(f"下载完成: {ok}/{len(urls)} 成功")
        except StopRequested:
            self._log("任务已停止。")
        except Exception as exc:
            self._log(f"下载出错: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            self.after(0, lambda: self._set_idle("下载完成"))

    def _on_list_formats(self):
        urls = self._get_urls()
        if not urls:
            self._log("请输入至少一个 URL。")
            return
        self._run_in_thread(lambda: self._do_list_formats(urls), "查询格式中...")

    def _do_list_formats(self, urls: list[str]):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        redirector = StdoutRedirector(self._log_queue)
        sys.stdout = redirector
        sys.stderr = redirector
        try:
            scraper = self._build_scraper()
            for i, url in enumerate(urls, 1):
                if self._stop_event.is_set():
                    self._log("任务已停止。")
                    break
                self._log(f"[{i}/{len(urls)}] 查询格式: {url}")
                scraper.list_formats(url)
        except StopRequested:
            self._log("任务已停止。")
        except Exception as exc:
            self._log(f"查询出错: {exc}")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            self.after(0, lambda: self._set_idle("查询完成"))


    # ── 本地 API 服务 ──────────────────────────────────────────

    def _start_api_server(self):
        APIHandler.gui = self
        try:
            self._http_server = HTTPServer(("127.0.0.1", self.API_PORT), APIHandler)
            t = threading.Thread(target=self._http_server.serve_forever, daemon=True)
            t.start()
            self._log(f"浏览器扩展 API 已启动: http://127.0.0.1:{self.API_PORT}")
        except OSError as exc:
            self._log(f"API 服务启动失败（端口 {self.API_PORT} 可能被占用）: {exc}")

    def _handle_extension_task(self, url: str, action: str, quality: str, cookies_text: str):
        self.url_textbox.delete("1.0", "end")
        self.url_textbox.insert("1.0", url)
        self.quality_var.set(quality)

        if cookies_text.strip():
            try:
                lines = [l for l in cookies_text.splitlines() if l.strip()]
                if lines:
                    f = tempfile.NamedTemporaryFile(
                        mode="w", suffix=".txt", prefix="vs_cookies_", delete=False
                    )
                    f.write("# Netscape HTTP Cookie File\n")
                    f.write("\n".join(lines) + "\n")
                    f.close()
                    self.cookies_var.set(f.name)
                    domains = {l.split("\t")[0].lstrip(".") for l in lines if "\t" in l}
                    self._log(f"已接收浏览器 Cookies（{len(lines)} 条，域名: {', '.join(sorted(domains))}）")
                else:
                    self.cookies_var.set("cookies.txt")
                    self._log("浏览器未提供 Cookies，使用默认设置")
            except Exception as exc:
                self._log(f"处理扩展 Cookies 失败: {exc}")

        self._log(f"来自浏览器扩展: {action} - {url}")
        if action == "download":
            self._on_download()
        else:
            self._on_extract()


def _get_install_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path.home() / ".local" / "share"
    return base / "VideoScraper"


def _get_install_path() -> Path:
    name = "video_scraper_gui.exe" if sys.platform == "win32" else "video_scraper_gui"
    return _get_install_dir() / name


def _try_show_running_gui() -> bool:
    """尝试聚焦已运行的 GUI 实例，成功返回 True。"""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{VideoScraperGUI.API_PORT}/api/show")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _register_protocol_handler():
    """注册 videoscraper:// 自定义协议处理器（仅打包环境下执行）。"""
    if not getattr(sys, "frozen", False):
        return

    exe_path = _get_install_path().resolve()
    if not exe_path.exists():
        return

    if sys.platform == "win32":
        try:
            import winreg
            key_path = r"Software\Classes\videoscraper"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Video Scraper Protocol")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\shell\open\command") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}" "%1"')
        except Exception:
            pass
    else:
        desktop_dir = Path.home() / ".local" / "share" / "applications"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        desktop_file = desktop_dir / "videoscraper.desktop"
        desktop_file.write_text(
            "[Desktop Entry]\n"
            "Name=Video Scraper\n"
            f"Exec={exe_path} %u\n"
            "Type=Application\n"
            "MimeType=x-scheme-handler/videoscraper;\n"
            "NoDisplay=true\n"
        )
        try:
            subprocess.run(
                ["xdg-mime", "default", "videoscraper.desktop", "x-scheme-handler/videoscraper"],
                check=False, capture_output=True,
            )
        except FileNotFoundError:
            pass


def main():
    # 处理 videoscraper:// 协议启动参数
    protocol_launch = any(arg.startswith("videoscraper://") for arg in sys.argv[1:])
    if protocol_launch:
        if _try_show_running_gui():
            sys.exit(0)
        # GUI 未运行，继续启动

    # 打包环境下的安装/更新逻辑
    if getattr(sys, "frozen", False):
        current_path = Path(sys.executable).resolve()
        install_path = _get_install_path().resolve()

        if current_path != install_path:
            # 当前不是从安装路径运行 → 执行安装/更新
            install_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(current_path), str(install_path))
            if sys.platform != "win32":
                install_path.chmod(install_path.stat().st_mode | 0o755)
            # 从安装路径启动
            subprocess.Popen([str(install_path)])
            sys.exit(0)

    app = VideoScraperGUI()

    # 打包环境下注册协议处理器并显示版本信息
    if getattr(sys, "frozen", False):
        install_path = _get_install_path().resolve()
        _register_protocol_handler()
        app._log(f"Video Scraper v{APP_VERSION}，安装路径: {install_path}")

    app.mainloop()


if __name__ == "__main__":
    main()
