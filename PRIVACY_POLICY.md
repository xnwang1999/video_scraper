# Privacy Policy - Video Scraper Helper Extension

**Last Updated: 2026-03-16**

## Overview

Video Scraper Helper is a browser extension that assists users in sending video URLs and cookies to the Video Scraper GUI desktop application running on the user's local machine. This privacy policy explains how the extension handles data.

## Data Collection and Usage

### What data is accessed

- **Current page URL**: The URL of the active browser tab, used to send to the local desktop application for video downloading.
- **Cookies**: Cookies from the current website domain (and Google domains when visiting YouTube), used solely for video download authentication.

### How data is used

All data is processed **exclusively on your local machine**:

- The extension sends data only to `127.0.0.1` (localhost) on a user-configured port (default: 9527).
- **No data is sent to any external server, third-party service, or remote endpoint.**
- Cookies are transmitted to the local desktop application in Netscape format for authentication purposes only.

### Data storage

- The extension does **not** store any cookies, URLs, or browsing history.
- The only data persisted is the user-configured port number, saved via the browser's local storage API.

## Data Sharing

- **No data is shared with third parties.**
- **No data leaves your local machine.**
- **No analytics, telemetry, or tracking of any kind is implemented.**

## Permissions Explained

| Permission | Purpose |
|-----------|---------|
| `activeTab` | Read the URL of the current tab to send to the local desktop application |
| `cookies` | Read cookies for the current site to provide authentication for video downloads |
| `<all_urls>` (host permission) | Required to read cookies from any video website the user visits |

## Security

- All communication occurs over `http://127.0.0.1`, which never leaves the local machine.
- The extension contains no external network requests, no CDN resources, and no remote scripts.

## Children's Privacy

This extension does not knowingly collect any personal information from children under 13.

## Changes to This Policy

Any changes to this privacy policy will be posted in this repository. The "Last Updated" date at the top will be revised accordingly.

## Contact

If you have questions about this privacy policy, please open an issue on the [GitHub repository](https://github.com/xnwang1999/video_scraper/issues).

---

# 隐私政策 - Video Scraper Helper 浏览器扩展

**最后更新：2026-03-16**

## 概述

Video Scraper Helper 是一款浏览器扩展，帮助用户将视频 URL 和 Cookies 发送到运行在本机的 Video Scraper GUI 桌面端。本隐私政策说明扩展如何处理数据。

## 数据收集与使用

### 访问的数据

- **当前页面 URL**：当前浏览器标签页的 URL，用于发送到本地桌面端进行视频下载。
- **Cookies**：当前网站域名的 Cookies（访问 YouTube 时还包括 Google 域名下的认证 Cookies），仅用于视频下载认证。

### 数据处理方式

所有数据**仅在本机处理**：

- 扩展仅向 `127.0.0.1`（本机回环地址）的用户配置端口（默认 9527）发送数据。
- **不会将任何数据发送到外部服务器、第三方服务或远程端点。**
- Cookies 以 Netscape 格式传输到本地桌面端，仅用于认证目的。

### 数据存储

- 扩展**不存储**任何 Cookies、URL 或浏览历史。
- 唯一持久化的数据是用户配置的端口号，通过浏览器本地存储 API 保存。

## 数据共享

- **不与任何第三方共享数据。**
- **数据不会离开你的本机。**
- **未实现任何分析、遥测或跟踪功能。**

## 权限说明

| 权限 | 用途 |
|------|------|
| `activeTab` | 读取当前标签页的 URL 以发送到本地桌面端 |
| `cookies` | 读取当前站点的 Cookies 以提供视频下载认证 |
| `<all_urls>`（主机权限） | 需要读取用户访问的任意视频网站的 Cookies |

## 安全性

- 所有通信通过 `http://127.0.0.1` 进行，数据不会离开本机。
- 扩展不包含任何外部网络请求、CDN 资源或远程脚本。

## 政策变更

本隐私政策的任何变更都将发布在此仓库中，并更新顶部的"最后更新"日期。

## 联系方式

如有关于本隐私政策的问题，请在 [GitHub 仓库](https://github.com/xnwang1999/video_scraper/issues) 中提交 Issue。
