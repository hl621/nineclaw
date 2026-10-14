from datetime import datetime
from typing import *

from pydantic import BaseModel, Field


class PublishDateExtractResult(BaseModel):
    algorithm: str  # 所用算法（提取、猜测）
    datetime: datetime  # 发布时间


class ContentExtractResult(BaseModel):
    algorithm: str  # 所用算法（快速抽取、符号密度、规则抽取）
    content_xpath: str  # 正文 xpath
    content_text: Optional[str] = None  # 正文内容
    noise_xpath: List[str] = Field(default_factory=list)  # 噪声


class LinkItem(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None

    model_config = {"frozen": True}

    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        return isinstance(other, LinkItem) and self.url == other.url


class LinkExtractResult(BaseModel):
    link_xpath: str
    block_xpath: str
    link_items: Set[LinkItem] = Field(default_factory=set)


class MediaExtractResult(BaseModel):
    # audio_urls: List[str] = Field(default_factory=list)  # 音频链接
    video_urls: Set[str] = Field(default_factory=set)  # 视频链接
    image_urls: Set[str] = Field(default_factory=set)  # 图片链接
    file_urls: Set[str] = Field(default_factory=set)  # 文件链接


class ExtractResult(BaseModel):
    url: Optional[str] = None  # 链接
    title: Optional[str] = None  # 标题
    publish_date: Optional[PublishDateExtractResult] = None  # 发布时间
    content: Optional[ContentExtractResult] = None  # 正文
    media: Optional[MediaExtractResult] = None  # 媒体链接
    language: Optional[str] = None  # 语种

    def __str__(self):
        return f"""
=================
url:{self.url}
title:{self.title}
publish_date:{self.publish_date}
---
{self.content.content_text}
"""
