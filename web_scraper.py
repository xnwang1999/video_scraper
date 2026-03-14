#!/usr/bin/env python3
"""
Web Scraper - 获取公开网络数据的爬虫软件
支持多种数据格式导出，错误处理和重试机制
"""

import requests
import time
import json
import csv
import logging
import argparse
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("Warning: BeautifulSoup4 not found. HTML parsing will be limited.")

@dataclass
class ScrapedData:
    """数据结构用于存储爬取的信息"""
    url: str
    title: str = ""
    content: str = ""
    links: List[str] = None
    timestamp: str = ""
    
    def __post_init__(self):
        if self.links is None:
            self.links = []
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

class WebScraper:
    """主要的网络爬虫类"""
    
    def __init__(self, delay: float = 1.0, timeout: int = 10, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        self.scraped_data: List[ScrapedData] = []
    
    def get_page(self, url: str) -> Optional[requests.Response]:
        """获取网页内容，包含重试机制"""
        for attempt in range(self.retries):
            try:
                self.logger.info(f"Fetching: {url} (attempt {attempt + 1})")
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                self.logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt == self.retries - 1:
                    self.logger.error(f"Failed to fetch {url} after {self.retries} attempts")
                    return None
                time.sleep(2 ** attempt)  # 指数退避
        return None
    
    def parse_html(self, response: requests.Response) -> ScrapedData:
        """解析HTML内容"""
        data = ScrapedData(url=response.url)
        
        if HAS_BS4:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 提取标题
            title_tag = soup.find('title')
            if title_tag:
                data.title = title_tag.get_text().strip()
            
            # 提取主要内容
            content_parts = []
            for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                text = tag.get_text().strip()
                if text:
                    content_parts.append(text)
            data.content = '\n'.join(content_parts)
            
            # 提取链接
            for link in soup.find_all('a', href=True):
                absolute_url = urljoin(response.url, link['href'])
                data.links.append(absolute_url)
        else:
            # 简单的文本提取（如果没有BeautifulSoup）
            data.content = response.text[:1000]  # 限制长度
        
        return data
    
    def scrape_url(self, url: str) -> Optional[ScrapedData]:
        """爬取单个URL"""
        response = self.get_page(url)
        if not response:
            return None
        
        # 根据内容类型解析
        content_type = response.headers.get('content-type', '').lower()
        
        if 'html' in content_type:
            data = self.parse_html(response)
        elif 'json' in content_type:
            try:
                json_data = response.json()
                data = ScrapedData(
                    url=url,
                    title="JSON Data",
                    content=json.dumps(json_data, indent=2, ensure_ascii=False)
                )
            except json.JSONDecodeError:
                data = ScrapedData(url=url, content=response.text)
        else:
            data = ScrapedData(url=url, content=response.text[:1000])
        
        self.scraped_data.append(data)
        return data
    
    def scrape_urls(self, urls: List[str]) -> List[ScrapedData]:
        """批量爬取URL列表"""
        results = []
        
        for i, url in enumerate(urls):
            self.logger.info(f"Processing {i+1}/{len(urls)}: {url}")
            
            data = self.scrape_url(url)
            if data:
                results.append(data)
            
            # 添加延迟避免过于频繁的请求
            if i < len(urls) - 1:
                time.sleep(self.delay)
        
        return results
    
    def save_to_json(self, filename: str = "scraped_data.json"):
        """保存数据为JSON格式"""
        data_dicts = [asdict(item) for item in self.scraped_data]
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data_dicts, f, indent=2, ensure_ascii=False)
        self.logger.info(f"Data saved to {filename}")
    
    def save_to_csv(self, filename: str = "scraped_data.csv"):
        """保存数据为CSV格式"""
        if not self.scraped_data:
            self.logger.warning("No data to save")
            return
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['URL', 'Title', 'Content', 'Links', 'Timestamp'])
            
            for item in self.scraped_data:
                writer.writerow([
                    item.url,
                    item.title,
                    item.content.replace('\n', ' ')[:500],  # 限制内容长度
                    ';'.join(item.links[:5]),  # 只保存前5个链接
                    item.timestamp
                ])
        self.logger.info(f"Data saved to {filename}")
    
    def save_to_txt(self, filename: str = "scraped_data.txt"):
        """保存数据为文本格式"""
        with open(filename, 'w', encoding='utf-8') as f:
            for item in self.scraped_data:
                f.write(f"URL: {item.url}\n")
                f.write(f"Title: {item.title}\n")
                f.write(f"Timestamp: {item.timestamp}\n")
                f.write(f"Content:\n{item.content}\n")
                f.write(f"Links: {', '.join(item.links[:5])}\n")
                f.write("-" * 80 + "\n\n")
        self.logger.info(f"Data saved to {filename}")

def main():
    """命令行入口点"""
    parser = argparse.ArgumentParser(description="Web Scraper - 获取公开网络数据")
    parser.add_argument('urls', nargs='+', help='要爬取的URL列表')
    parser.add_argument('--delay', type=float, default=1.0, help='请求间延迟（秒）')
    parser.add_argument('--timeout', type=int, default=10, help='请求超时时间（秒）')
    parser.add_argument('--retries', type=int, default=3, help='重试次数')
    parser.add_argument('--output', choices=['json', 'csv', 'txt', 'all'], 
                       default='json', help='输出格式')
    parser.add_argument('--filename', default='scraped_data', help='输出文件名前缀')
    
    args = parser.parse_args()
    
    # 创建爬虫实例
    scraper = WebScraper(
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries
    )
    
    # 开始爬取
    print(f"开始爬取 {len(args.urls)} 个URL...")
    results = scraper.scrape_urls(args.urls)
    
    if results:
        print(f"成功爬取 {len(results)} 个页面")
        
        # 保存数据
        if args.output == 'json' or args.output == 'all':
            scraper.save_to_json(f"{args.filename}.json")
        if args.output == 'csv' or args.output == 'all':
            scraper.save_to_csv(f"{args.filename}.csv")
        if args.output == 'txt' or args.output == 'all':
            scraper.save_to_txt(f"{args.filename}.txt")
    else:
        print("没有成功爬取到数据")

if __name__ == "__main__":
    main()