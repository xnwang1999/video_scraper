# Video Scraper - 视频下载工具

一个功能完整的视频下载工具，支持多线程 m3u8 下载、AES-128 解密、跨平台打包。

## 功能特性

- **主流站点支持**: 基于 `yt-dlp`，覆盖大多数公开视频站点
- **音视频分离下载**: 自动处理音视频分离的资源（如 B站），下载后自动合并为完整视频
- **多线程 m3u8 下载**: 并发下载分片，支持 AES-128 加密流自动解密
- **智能回退**: `yt-dlp` 失败时自动回退到页面直链提取 + ffmpeg 下载
- **列表页批量发现**: 从列表页/首页自动提取资源链接，支持自定义正则和 CSS 选择器
- **实时进度显示**: 下载速度、已下载大小、耗时、分片进度
- **登录态支持**: 支持 `cookies.txt` 或从浏览器读取 cookies
- **跨平台打包**: 支持打包为 Windows/Linux/macOS 可执行文件（内嵌 ffmpeg）

## 预编译可执行文件

`dist/` 目录提供预编译的可执行文件，无需安装 Python 环境即可使用：

| 平台 | 文件 |
|------|------|
| Linux (x86_64) | `dist/video_scraper` |
| Windows (x64) | `dist/video_scraper.exe` |

## 项目结构

```
video_scraper/
├── README.md              # 项目说明文档
├── requirements.txt       # Python 依赖包列表
├── config.json            # 配置文件
├── video_scraper.py       # 视频下载工具主程序
├── video_scraper.spec     # PyInstaller 打包配置
├── build.py               # 跨平台构建脚本
└── downloads/             # 默认下载目录
```

## 安装

### 从源码运行

```bash
# 安装依赖
pip install -r requirements.txt

# 系统还需要安装 ffmpeg
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg
# Windows: 从 https://ffmpeg.org/download.html 下载
```

### 直接下载可执行文件

从 [Releases](https://github.com/xnwang1999/video_scraper/releases) 下载对应平台的可执行文件，开箱即用，无需安装 Python 或 ffmpeg。

## 使用方法

### 基本用法

```bash
# 提取视频信息（不下载）
python video_scraper.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 下载视频
python video_scraper.py "https://www.youtube.com/watch?v=VIDEO_ID" --download

# 指定质量
python video_scraper.py "URL" --download --quality 720p

# 使用浏览器 cookies
python video_scraper.py "URL" --download --browser chrome

# 查看可用格式
python video_scraper.py "URL" --list-formats
```

### 列表页批量发现与下载

```bash
# 发现列表页中的资源链接
python video_scraper.py "https://example.com/list" --discover --limit 20

# 用正则过滤链接
python video_scraper.py "https://example.com/list" --discover --url-pattern '/videos/\w+'

# 用 CSS 选择器限定区域
python video_scraper.py "https://example.com/list" --discover --css-selector 'div.content a'

# 发现并直接下载
python video_scraper.py "https://example.com/list" --discover-download --limit 50 --page-limit 5
```

### m3u8 直接转换

```bash
# 将远程 m3u8 URL 转为 mp4
python video_scraper.py "https://example.com/video.m3u8" --convert-m3u8
```

### 批量下载

```bash
# 从文件批量下载
python video_scraper.py --input-file urls.txt --download

# 多个 URL
python video_scraper.py "URL1" "URL2" "URL3" --download --quality 1080p
```

### Python 代码调用

```python
from video_scraper import VideoScraper

scraper = VideoScraper(quality="best", concurrent_fragments=8)

# 提取视频信息
info = scraper.scrape_video("https://www.youtube.com/watch?v=VIDEO_ID")
print(f"标题: {info.title}, 时长: {info.duration}")

# 下载视频
scraper.download_video("URL", output_path="./downloads/")

# 从列表页发现并下载
results = scraper.discover_and_download("https://example.com/list", limit=20)
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `urls` | 视频 URL 列表 | - |
| `--input-file` | 从文本文件读取 URL（每行一个） | - |
| `--download` | 下载视频文件 | False |
| `--quality` | 质量策略（best / 720p / worst） | best |
| `--list-formats` | 列出可用格式 | False |
| `--discover` | 从页面发现资源链接 | False |
| `--discover-download` | 发现并直接下载 | False |
| `--limit` | 发现链接数量限制 | 10 |
| `--page-limit` | 最大翻页数 | 1 |
| `--url-pattern` | 自定义 URL 正则过滤 | - |
| `--css-selector` | CSS 选择器限定提取区域 | - |
| `--convert-m3u8` | 将 m3u8 URL 转为 mp4 | False |
| `--download-path` | 下载保存路径 | ./downloads/ |
| `--cookies-file` | cookies 文件路径 | cookies.txt |
| `--browser` | 从浏览器读取 cookies | - |
| `--proxy` | 代理地址 | - |
| `--referer` | 自定义 Referer | - |
| `--audio-only` | 仅下载音频（mp3） | False |
| `--concurrent-fragments` | 分片并发数 | 4 |
| `--delay` | 批量下载间隔（秒） | 2.0 |
| `--timeout` | 请求超时（秒） | 30 |
| `--retries` | 请求重试次数 | 3 |
| `--output` | 元数据输出 JSON 文件 | video_data.json |

## 打包构建

```bash
# Linux/macOS（使用系统 ffmpeg）
python build.py --use-system-ffmpeg

# 自动下载 ffmpeg 静态版本
python build.py

# 不捆绑 ffmpeg（体积更小）
python build.py --no-ffmpeg

# onedir 模式（启动更快）
python build.py --onedir
```

构建产物在 `dist/` 目录。

## 支持的视频平台

| 平台 | 元数据提取 | 视频下载 | 说明 |
|------|-----------|----------|------|
| YouTube / Bilibili / Vimeo / TikTok / Instagram | ✅ | ✅ | 由 yt-dlp 提供 |
| X(Twitter) / Facebook / Dailymotion 等 | ✅ | ✅ | 由 yt-dlp 提供 |
| m3u8 流（含 AES-128 加密） | ✅ | ✅ | 多线程下载 + 解密 |
| 其他公开页面（含直链） | ✅ | ⚠️ | 通用直链提取兜底 |

## 技术依赖

- **requests**: HTTP 请求处理
- **beautifulsoup4**: HTML 解析
- **yt-dlp**: 视频站点信息提取和下载
- **pycryptodome**: AES-128 解密
- **tqdm**: 进度条显示
- **lxml**: XML/HTML 解析器
- **ffmpeg**: 视频格式转换与 m3u8 处理

## Cookies 配置（重要）

部分视频网站（如 **B站 bilibili**）启用了反爬机制，未携带有效 Cookie 会返回 `HTTP 412` 错误，导致提取和下载失败。以下是配置 Cookies 的详细步骤。

### 方法一：导出 cookies.txt 文件（推荐）

适用于所有平台（Windows / Linux / macOS），尤其是 **WSL 用户**（WSL 无法直接读取 Windows 浏览器的 Cookie 数据库）。

#### 第 1 步：安装浏览器扩展

根据你使用的浏览器，安装对应的 Cookie 导出扩展：

| 浏览器 | 扩展名称 | 安装链接 |
|--------|---------|---------|
| Chrome | Get cookies.txt LOCALLY | [Chrome Web Store](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) |
| Edge | Get cookies.txt LOCALLY | [Edge Add-ons](https://microsoftedge.microsoft.com/addons/detail/get-cookiestxt-locally/jajhpmkncogjbjibbbpdofodndhmchgh) |
| Firefox | cookies.txt | [Firefox Add-ons](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/) |

> **注意**：请确保导出的是 **Netscape 格式**（文件开头应有 `# Netscape HTTP Cookie File`），而非 JSON 格式。

#### 第 2 步：导出 Cookie

1. 打开浏览器，访问目标网站（如 `bilibili.com`）并**登录账号**
2. 点击扩展图标，选择 **Export** / **导出**
3. 将导出的文件保存为 `cookies.txt`

#### 第 3 步：放置文件

将 `cookies.txt` 放到以下任一位置：

- 与 `video_scraper` 可执行文件**同级目录**（默认查找路径）
- 或通过 `--cookies-file` 参数指定路径：

```bash
./video_scraper "URL" --download --cookies-file /path/to/cookies.txt
```

#### 导出文件格式示例

正确的 Netscape 格式 `cookies.txt` 内容类似：

```
# Netscape HTTP Cookie File
.bilibili.com	TRUE	/	FALSE	1735689600	buvid3	xxxxxxxx-xxxx-xxxx-xxxx
.bilibili.com	TRUE	/	FALSE	1735689600	SESSDATA	xxxxxxxxxxxxxx
.bilibili.com	TRUE	/	FALSE	1735689600	bili_jct	xxxxxxxxxxxxxx
```

### 方法二：从浏览器自动读取（非 WSL 环境）

如果你在本机（非 WSL）运行，可以直接从浏览器读取 Cookie：

```bash
./video_scraper "URL" --download --browser chrome
```

`--browser` 支持的选项：`chrome` / `firefox` / `safari` / `edge` / `chromium`

> **WSL 用户注意**：WSL 下无法访问 Windows 浏览器的 Cookie 数据库，请使用方法一导出 `cookies.txt`。

### 需要 Cookies 的常见站点

| 站点 | 是否必须 | 说明 |
|------|---------|------|
| B站 (bilibili) | ✅ 必须 | 未携带 Cookie 会返回 HTTP 412，无法访问 |
| YouTube | ⚠️ 部分需要 | 年龄限制 / 会员视频需要登录态 |
| Instagram / X(Twitter) | ⚠️ 部分需要 | 私密内容需要登录态 |
| 其他公开站点 | ❌ 不需要 | 公开内容通常无需 Cookie |

## 注意事项

- 仅用于下载公开可访问的视频内容
- 请遵守目标网站服务条款与当地法律法规
- 建议安装最新版 `yt-dlp` 与 `ffmpeg` 以提升成功率
- 某些站点需要登录态，请使用 `cookies.txt` 或 `--browser`
- Cookies 会过期，如遇到之前可用的站点突然失败，请重新导出 `cookies.txt`
