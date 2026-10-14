"""
网页抓取服务
实现网页HTML抓取的业务逻辑，支持静态抓取和JS渲染
"""
import httpx
import time
import os
from furl import furl
from typing import Dict, Any, Optional
from .base_service import BaseService
# from .exceptions import FetchServiceError, NetworkError, ParseError
from models import FetchResult
from config import config
from utils.content_extractor import extract_content_from_html
from utils.enhanced_html_cleaner import clean_html_to_text


class FetchService(BaseService):
    """网页抓取服务类"""
    
    
    def __init__(self):
        super().__init__("FetchService")
        # 从配置文件加载设置
        self.timeout = config.timeout
        self.browserless_url = config.browserless_url.rstrip('/')
        self.browserless_token = config.browserless_token
        self.proxy_config = config.get_proxy_config()
        
        # User-Agent 配置
        self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    
    async def fetch(self, url: str, render: bool = False) -> FetchResult:
        """
        抓取网页内容
        
        Args:
            url: 目标URL
            render: 是否启用JS渲染（如果为False，会先尝试静态抓取，失败时自动切换到JS渲染）
            
        Returns:
            抓取结果对象
        """
        start_time = time.time()
        
        try:
            self.log_info(f"Fetching URL: {url}, render: {render}")
            
            # 验证URL格式
            if not self._validate_url(url):
                raise ValueError(f"Invalid URL format: {url}")
            
            # 如果明确指定了render=True，直接使用JS渲染
            if render:
                result = await self._fetch_with_render(url)
            else:
                # 默认先尝试静态抓取
                result = await self._fetch_static(url)
                
                # 检查静态抓取是否失败，如果失败则尝试JS渲染
                if self._should_fallback_to_render(result):
                    self.log_info(f"Static fetch failed, falling back to JS render for URL: {url}")
                    result = await self._fetch_with_render(url)
            
            # 计算抓取耗时
            fetch_time = time.time() - start_time
            result.fetch_time = fetch_time
            
            return result
                
        except Exception as e:
            # 返回错误结果
            return FetchResult(
                url=url,
                status_code=0,
                fetch_time=time.time() - start_time,
                render_mode=render,
                api_method="error",
                cleaned_content=None,
                extraction_algorithm=None,
                extraction_time=0.0
            )
    
    async def _fetch_static(self, url: str) -> FetchResult:
        """
        静态HTML抓取
        
        Args:
            url: 目标URL
            
        Returns:
            抓取结果
        """
        headers = {
            'User-Agent': self.user_agent,
            'Referer': furl(url).remove(args=True, path=True, fragment=True).tostr()
        }
        
        try:
            # 禁用 SSL 验证（如果遇到 SSL 问题）
            verify_ssl = os.getenv("VERIFY_SSL", "true").lower() == "true"
            async with httpx.AsyncClient(
                proxy=self.proxy_config, 
                timeout=self.timeout,
                verify=verify_ssl
            ) as client:
                response = await client.get(url, headers=headers, follow_redirects=True)
                
                # 处理HTML内容
                cleaned_content, algorithm, extraction_time = self._process_html_content(response.text)
                
                return FetchResult(
                    url=str(response.url),
                    final_url=str(response.url),
                    status_code=response.status_code,
                    content_type=response.headers.get('content-type'),
                    content_length=len(response.content),
                    encoding=response.encoding,
                    headers=dict(response.headers),
                    fetch_time=0.0,  # 会在主方法中设置
                    render_mode=False,
                    api_method="static",
                    cleaned_content=cleaned_content,
                    extraction_algorithm=algorithm,
                    extraction_time=extraction_time
                )
                
        except Exception as e:
            # 返回错误结果
            return FetchResult(
                url=url,
                status_code=0,
                fetch_time=0.0,
                render_mode=False,
                api_method="static_error",
                cleaned_content=None,
                extraction_algorithm=None,
                extraction_time=0.0
            )
            
        
    
    async def _fetch_with_render(self, url: str) -> FetchResult:
        """
        JS渲染抓取
        
        Args:
            url: 目标URL
            
        Returns:
            抓取结果
        """
        try:
            # 检查 browserless 配置
            if not self.browserless_token:
                error_msg = "Browserless token is required for JS rendering. Please set BROWSERLESS_TOKEN environment variable."
                self.log_error(error_msg)
                raise ValueError(error_msg)
            
            # 构建 browserless API URL
            api_url = f"{self.browserless_url}/content?token={self.browserless_token}"
            
            # 设置请求头和数据
            headers = {
                "Cache-Control": "no-cache",
                "Content-Type": "application/json"
            }
            data = {"url": url}
            
            self.log_info(f"Fetching with render from browserless: {url}")
            self.log_info(f"API URL: {api_url}")
            
            # 发送异步请求
            # 禁用 SSL 验证（如果遇到 SSL 问题）
            verify_ssl = os.getenv("VERIFY_SSL", "true").lower() == "true"
            async with httpx.AsyncClient(
                proxy=self.proxy_config, 
                timeout=self.timeout,
                verify=verify_ssl
            ) as client:
                response = await client.post(api_url, headers=headers, json=data)
                
                self.log_info(f"Response status: {response.status_code}")
                self.log_info(f"Response headers: {dict(response.headers)}")
                self.log_info(f"Response content type: {response.headers.get('content-type', 'unknown')}")
                
                if response.status_code != 200:
                    error_msg = f"Browserless API returned status {response.status_code}: {response.text}"
                    self.log_error(error_msg)
                    raise Exception(error_msg)
                
                # browserless 直接返回 HTML 内容
                html_content = response.text
                
                self.log_info(f"Successfully fetched content, length: {len(html_content)}")
                
                # 处理HTML内容
                cleaned_content, algorithm, extraction_time = self._process_html_content(html_content)
                
                return FetchResult(
                    url=url,
                    final_url=url,
                    status_code=200,
                    content_type="text/html",
                    content_length=len(html_content),
                    encoding="utf-8",
                    headers={},
                    fetch_time=0.0,
                    render_mode=True,
                    api_method="content",
                    cleaned_content=cleaned_content,
                    extraction_algorithm=algorithm,
                    extraction_time=extraction_time
                )
                
        except Exception as e:
            error_msg = f"Error while fetching with render: {e}"
            self.log_error(error_msg)
            raise Exception(error_msg)

    def _process_html_content(self, html_content: str) -> tuple[str, str, str]:
        """
        处理HTML内容，提取清洗后的正文
        
        Args:
            html_content: HTML内容
            
        Returns:
            (cleaned_content, algorithm, extraction_time)
        """
        if not html_content:
            return None, None, 0.0
        
        start_time = time.time()
        
        try:
            # 使用正文提取器提取正文
            extract_result = extract_content_from_html(html_content, algorithm='auto')
            
            if extract_result and extract_result.content_text:
                # 进一步清洗提取的正文
                cleaned_content = clean_html_to_text(extract_result.content_text)
                extraction_time = time.time() - start_time
                
                self.log_info(f"Content extracted using {extract_result.algorithm} algorithm, "
                            f"length: {len(cleaned_content)}, time: {extraction_time:.3f}s")
                
                return cleaned_content, extract_result.algorithm, extraction_time
            else:
                # 如果正文提取失败，使用基础HTML清洗
                cleaned_content = clean_html_to_text(html_content)
                extraction_time = time.time() - start_time
                
                self.log_info(f"Content extraction failed, using basic cleaning, "
                            f"length: {len(cleaned_content)}, time: {extraction_time:.3f}s")
                
                return cleaned_content, 'basic_clean', extraction_time
        
        except Exception as e:
            self.log_error(f"Error processing HTML content: {e}")
            # 降级到基础清洗
            try:
                cleaned_content = clean_html_to_text(html_content)
                extraction_time = time.time() - start_time
                return cleaned_content, 'basic_clean', extraction_time
            except Exception:
                return None, None, 0.0
    
    def _should_fallback_to_render(self, result: FetchResult) -> bool:
        """
        判断是否应该回退到JS渲染模式
        
        Args:
            result: 静态抓取的结果
            
        Returns:
            是否应该回退
        """
        # 检查状态码是否为403（禁止访问）
        if result.status_code == 403:
            self.log_info(f"Status code 403 detected, will fallback to render")
            return True
        
        # 检查内容是否为空或过短
        if not result.cleaned_content or len(result.cleaned_content.strip()) < 50:
            self.log_info(f"Content too short or empty (length: {len(result.cleaned_content or '')}), will fallback to render")
            return True
        
        # 检查是否包含常见的反爬虫标识
        if result.cleaned_content:
            anti_bot_indicators = [
                "请启用JavaScript",
                "JavaScript is disabled",
                "请开启JavaScript",
                "Access Denied",
                "403 Forbidden",
                "Cloudflare",
                "请验证您是人类"
            ]
            
            content_lower = result.cleaned_content.lower()
            for indicator in anti_bot_indicators:
                if indicator.lower() in content_lower:
                    self.log_info(f"Anti-bot indicator detected: {indicator}, will fallback to render")
                    return True
        
        return False

    def _validate_url(self, url: str) -> bool:
        """
        验证URL格式
        
        Args:
            url: 待验证的URL
            
        Returns:
            是否有效
        """
        try:
            furl(url)
            return True
        except Exception:
            return False
