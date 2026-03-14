# Web Scraper - 网络爬虫工具

一个功能完整的Python网络爬虫软件，用于获取公开的网络数据，特别支持视频网站。

## 功能特性

### 通用爬虫 (web_scraper.py)
- ✅ **多格式输出**: 支持JSON、CSV、TXT格式导出
- ✅ **智能解析**: 自动识别HTML、JSON等内容类型
- ✅ **错误处理**: 内置重试机制和异常处理
- ✅ **速率限制**: 可配置请求间延迟，避免服务器压力
- ✅ **批量处理**: 支持同时爬取多个URL

### 视频爬虫 (video_scraper.py)
- 🎥 **主流站点优先支持**: 基于 `yt-dlp`，覆盖大多数公开视频站点（非加密）
- 🎥 **高稳定下载**: 重试、分片并发、断点续传、格式合并（需本机 ffmpeg）
- 🎥 **登录态支持**: 支持 `cookies.txt` 或从浏览器读取 cookies
- 🎥 **通用兜底提取**: `yt-dlp` 失败时自动回退到页面直链提取
- 🎥 **格式探测**: 支持查看可下载格式与清晰度

## 项目结构

```
web_scraper/
├── README.md           # 项目说明文档
├── requirements.txt    # Python依赖包列表
├── config.json        # 配置文件
├── cookies.txt        # Cookie存储文件
├── web_scraper.py     # 通用网站爬虫
├── video_scraper.py   # 视频网站爬虫
├── video_data.json    # 视频数据输出文件
└── downloads/         # 视频下载目录
```

## 安装依赖

### 推荐使用虚拟环境

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 直接安装

```bash
pip install -r requirements.txt
```

## 使用方法

### 通用网站爬虫

```bash
# 爬取普通网站
python web_scraper.py https://example.com

# 批量爬取多个网站
python web_scraper.py https://example.com https://httpbin.org/json --output all
```

### 视频网站爬虫

```bash
# 提取视频信息（不下载）
python video_scraper.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 下载视频（默认 best）
python video_scraper.py "https://www.youtube.com/watch?v=VIDEO_ID" --download

# 批量处理多个视频
python video_scraper.py \
    "https://www.youtube.com/watch?v=VIDEO1" \
    "https://www.bilibili.com/video/VIDEO2" \
    --download --quality 720p

# 使用浏览器 cookies（部分站点需要登录态）
python video_scraper.py "URL" --download --browser chrome

# 查看可用格式
python video_scraper.py "URL" --list-formats
```

### Python代码使用

```python
# 普通网站爬虫
from web_scraper import WebScraper
scraper = WebScraper()
data = scraper.scrape_url("https://example.com")

# 视频网站爬虫
from video_scraper import VideoScraper
video_scraper = VideoScraper()
video_info = video_scraper.scrape_video("https://www.youtube.com/watch?v=VIDEO_ID")
print(f"标题: {video_info.title}")
print(f"时长: {video_info.duration}")
```

## 支持的视频平台

| 平台 | 元数据提取 | 视频下载 | 说明 |
|------|-----------|----------|------|
| YouTube / Bilibili / Vimeo / TikTok / Instagram | ✅ | ✅ | 由 yt-dlp 提供 |
| X(Twitter) / Facebook / Dailymotion 等 | ✅ | ✅ | 由 yt-dlp 提供 |
| 其他公开页面（含直链） | ✅ | ⚠️ | 由通用直链提取兜底 |

## 视频信息输出示例

```json
{
  "url": "https://www.youtube.com/watch?v=example",
  "title": "示例视频标题",
  "description": "视频描述内容...",
  "duration": "300",
  "view_count": "10000",
  "upload_date": "20240101",
  "uploader": "频道名称",
  "thumbnail_url": "https://img.youtube.com/vi/example/maxresdefault.jpg",
  "video_urls": ["https://..."],
  "tags": ["标签1", "标签2"],
  "timestamp": "2024-01-01 12:00:00"
}
```

## 配置说明

项目使用 `config.json` 文件进行配置，包含以下设置：

### 默认设置 (default_settings)
- `delay`: 请求间延迟时间（秒），默认1.0
- `timeout`: 请求超时时间（秒），默认10
- `retries`: 重试次数，默认3
- `output_format`: 输出格式，支持json/csv/txt
- `max_content_length`: 最大内容长度限制
- `max_links_per_page`: 每页最大链接数量

### 请求头设置 (headers)
- `User-Agent`: 浏览器标识，用于模拟真实浏览器访问

### 域名控制
- `allowed_domains`: 允许爬取的域名列表（为空则不限制）
- `blocked_domains`: 禁止爬取的域名列表

配置文件示例：
```json
{
  "default_settings": {
    "delay": 1.0,
    "timeout": 10,
    "retries": 3,
    "output_format": "json"
  },
  "headers": {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
  }
}
```

## 命令行参数

### video_scraper.py 参数
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `urls` | 视频URL列表 | - |
| `--input-file` | 从文本文件读取URL（每行一个） | - |
| `--download` | 下载视频文件 | False |
| `--quality` | 质量策略（如 best / 720p / worst） | best |
| `--list-formats` | 列出可用格式 | False |
| `--download-path` | 下载保存路径 | ./downloads/ |
| `--cookies-file` | cookies 文件路径 | cookies.txt |
| `--browser` | 从浏览器读取 cookies（chrome/firefox/edge...） | - |
| `--proxy` | 代理地址 | - |
| `--referer` | 自定义 Referer | - |
| `--audio-only` | 仅下载音频（mp3） | False |
| `--concurrent-fragments` | 分片并发数 | 4 |
| `--timeout` | 请求超时（秒） | 30 |
| `--retries` | 请求重试次数 | 3 |
| `--output` | 元数据输出JSON文件 | video_data.json |

## 注意事项

⚠️ **重要提醒**：
- 仅用于下载公开可访问、非加密的视频内容
- 请遵守目标网站服务条款与当地法律法规
- 建议安装最新版 `yt-dlp` 与 `ffmpeg` 以提升成功率
- 某些站点需要登录态，请使用 `cookies.txt` 或 `--browser`
- 受 DRM / 平台加密保护的视频不在本工具支持范围内

## 示例用法

```bash
# 获取YouTube视频信息
python video_scraper.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# 下载 B 站视频
python video_scraper.py "https://www.bilibili.com/video/BV1xx411c7mD" --download --quality 1080p

# 批量处理并指定质量
python video_scraper.py \
    "https://www.youtube.com/watch?v=VIDEO1" \
    "https://www.youtube.com/watch?v=VIDEO2" \
    --download --quality 1080p --download-path ./my_videos/

# 从文件批量下载
python video_scraper.py --input-file ./urls.txt --download --quality best

# 仅提取元数据，不下载
python video_scraper.py "URL1" "URL2" --output video_data.json
```

## 常见问题和故障排除

### 1. 安装问题
**问题**: pip安装依赖失败
```bash
# 解决方案：更新pip并使用国内镜像
pip install --upgrade pip
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
```

### 2. 视频下载问题
**问题**: yt-dlp下载失败或格式不支持
```bash
# 更新yt-dlp到最新版本
pip install --upgrade yt-dlp

# 安装 ffmpeg（Ubuntu）
sudo apt-get update && sudo apt-get install -y ffmpeg

# 查看可用格式
yt-dlp -F "视频URL"

# 指定格式下载
python video_scraper.py "URL" --download --quality "best[height<=720]"
```

### 3. 网络连接问题
**问题**: 请求超时或连接被拒绝
- 检查网络连接
- 增加config.json中的timeout值
- 调整delay延迟时间避免被反爬虫
- 使用代理（修改headers设置）

### 4. 权限问题
**问题**: 无法访问某些网站或被反爬虫拦截
- 检查目标网站的robots.txt
- 调整User-Agent设置
- 增加请求延迟时间
- 使用cookies.txt文件保存登录状态

### 5. 输出文件问题
**问题**: 文件保存失败或格式错误
- 检查输出目录权限
- 确保磁盘空间充足
- 验证文件名是否包含非法字符

## 技术依赖

- **requests**: HTTP请求处理
- **beautifulsoup4**: HTML解析
- **yt-dlp**: 视频网站信息提取和下载（推荐）
- **lxml**: XML/HTML解析器