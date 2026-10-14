"""
基础服务类
提供通用的服务层功能，包括日志、错误处理、配置管理等
"""

import logging
from abc import ABC
from typing import Any, Dict, Optional


class BaseService(ABC):
    """基础服务类"""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"services.{name}")
    
    def log_info(self, message: str, **kwargs):
        """记录信息日志"""
        self.logger.info(f"[{self.name}] {message}", extra=kwargs)
    
    def log_error(self, message: str, **kwargs):
        """记录错误日志"""
        self.logger.error(f"[{self.name}] {message}", extra=kwargs)
    
    def log_warning(self, message: str, **kwargs):
        """记录警告日志"""
        self.logger.warning(f"[{self.name}] {message}", extra=kwargs)
    
    def handle_error(self, error: Exception, context: str = "") -> Dict[str, Any]:
        """统一错误处理"""
        error_msg = f"Error in {self.name}: {str(error)}"
        if context:
            error_msg = f"{context} - {error_msg}"
        
        self.log_error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "error_type": type(error).__name__
        }
