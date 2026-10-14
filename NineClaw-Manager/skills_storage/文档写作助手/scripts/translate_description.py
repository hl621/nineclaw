#!/usr/bin/env python3
"""
Description Translator Helper
Translates common Chinese description patterns to English.
Works offline using pattern matching and templates.
"""

import re
import sys

# Common verb translations
VERB_MAP = {
    # 实现类
    '实现': 'Implement',
    '完成': 'Complete',
    '达成': 'Achieve',
    '执行': 'Execute',
    '运行': 'Run',
    
    # 创建类
    '创建': 'Create',
    '生成': 'Generate',
    '建立': 'Build',
    '构造': 'Construct',
    '初始化': 'Initialize',
    '实例化': 'Instantiate',
    
    # 处理类
    '处理': 'Process',
    '解析': 'Parse',
    '分析': 'Analyze',
    '转换': 'Convert',
    '变换': 'Transform',
    '编码': 'Encode',
    '解码': 'Decode',
    '压缩': 'Compress',
    '解压': 'Decompress',
    
    # 验证类
    '验证': 'Validate',
    '校验': 'Verify',
    '检查': 'Check',
    '确认': 'Confirm',
    '确保': 'Ensure',
    '断言': 'Assert',
    
    # 获取类
    '获取': 'Fetch',
    '读取': 'Read',
    '查询': 'Query',
    '检索': 'Retrieve',
    '提取': 'Extract',
    '加载': 'Load',
    '导入': 'Import',
    '接收': 'Receive',
    
    # 设置类
    '设置': 'Set',
    '配置': 'Configure',
    '更新': 'Update',
    '修改': 'Modify',
    '编辑': 'Edit',
    '调整': 'Adjust',
    '保存': 'Save',
    '写入': 'Write',
    '导出': 'Export',
    '发送': 'Send',
    '提交': 'Submit',
    '推送': 'Push',
    
    # 删除类
    '删除': 'Delete',
    '移除': 'Remove',
    '清空': 'Clear',
    '销毁': 'Destroy',
    '释放': 'Release',
    
    # 计算类
    '计算': 'Calculate',
    '统计': 'Count',
    '累加': 'Sum',
    '求和': 'Sum',
    '平均': 'Average',
    '比较': 'Compare',
    '排序': 'Sort',
    '过滤': 'Filter',
    '搜索': 'Search',
    '查找': 'Find',
    '匹配': 'Match',
    '替换': 'Replace',
    
    # 控制类
    '启动': 'Start',
    '停止': 'Stop',
    '暂停': 'Pause',
    '恢复': 'Resume',
    '重启': 'Restart',
    '取消': 'Cancel',
    '中断': 'Interrupt',
    '跳过': 'Skip',
    '重试': 'Retry',
    
    # 其他
    '显示': 'Display',
    '展示': 'Show',
    '隐藏': 'Hide',
    '渲染': 'Render',
    '绘制': 'Draw',
    '打印': 'Print',
    '记录': 'Log',
    '监控': 'Monitor',
    '跟踪': 'Track',
    '监听': 'Listen',
    '等待': 'Wait',
    '阻塞': 'Block',
    '同步': 'Synchronize',
    '异步': 'Asynchronous',
    '并行': 'Parallel',
    '批量': 'Batch',
}

# Common noun translations
NOUN_MAP = {
    '用户': 'user',
    '管理员': 'admin',
    '客户': 'customer',
    '账户': 'account',
    '权限': 'permission',
    '角色': 'role',
    '配置': 'config',
    '设置': 'settings',
    '参数': 'parameters',
    '选项': 'options',
    '数据': 'data',
    '数据库': 'database',
    '记录': 'records',
    '条目': 'entries',
    '列表': 'list',
    '数组': 'array',
    '集合': 'collection',
    '字典': 'dictionary',
    '映射': 'map',
    '缓存': 'cache',
    '文件': 'file',
    '文件夹': 'directory',
    '路径': 'path',
    '名称': 'name',
    '标题': 'title',
    '描述': 'description',
    '内容': 'content',
    '信息': 'info',
    '消息': 'message',
    '通知': 'notification',
    '邮件': 'email',
    '请求': 'request',
    '响应': 'response',
    '结果': 'result',
    '返回值': 'return value',
    '错误': 'error',
    '异常': 'exception',
    '日志': 'log',
    '报告': 'report',
    '表格': 'table',
    '视图': 'view',
    '页面': 'page',
    '接口': 'interface',
    '类': 'class',
    '方法': 'method',
    '函数': 'function',
    '变量': 'variable',
    '属性': 'property',
    '字段': 'field',
    '类型': 'type',
    '格式': 'format',
    '模板': 'template',
    '组件': 'component',
    '模块': 'module',
    '服务': 'service',
    '应用': 'application',
    '系统': 'system',
    '网络': 'network',
    '服务器': 'server',
    '客户端': 'client',
    '浏览器': 'browser',
    '设备': 'device',
    '资源': 'resource',
    '内存': 'memory',
    '存储': 'storage',
    '文件系统': 'filesystem',
    '进程': 'process',
    '线程': 'thread',
    '任务': 'task',
    '作业': 'job',
    '队列': 'queue',
    '调度': 'schedule',
    '定时器': 'timer',
    '时间': 'time',
    '日期': 'date',
    '字符串': 'string',
    '数字': 'number',
    '整数': 'integer',
    '浮点数': 'float',
    '布尔值': 'boolean',
    '对象': 'object',
    'JSON': 'JSON',
    'XML': 'XML',
    'HTML': 'HTML',
    'CSS': 'CSS',
    'SQL': 'SQL',
    'API': 'API',
    'URL': 'URL',
    'ID': 'ID',
    'UUID': 'UUID',
    '密钥': 'key',
    '令牌': 'token',
    '密码': 'password',
    '验证码': 'captcha',
    '会话': 'session',
    'Cookie': 'cookie',
    '头部': 'header',
    '主体': 'body',
    '表单': 'form',
    '输入': 'input',
    '输出': 'output',
    '上传': 'upload',
    '下载': 'download',
    '导入': 'import',
    '导出': 'export',
    '编码': 'encoding',
    '压缩': 'compression',
    '加密': 'encryption',
    '解密': 'decryption',
    '签名': 'signature',
    '验证': 'verification',
    '校验': 'checksum',
    '索引': 'index',
    '主键': 'primary key',
    '外键': 'foreign key',
    '关联': 'relationship',
    '连接': 'join',
    '事务': 'transaction',
    '锁': 'lock',
    '并发': 'concurrency',
    '同步': 'sync',
    '异步': 'async',
    '事件': 'event',
    '回调': 'callback',
    '监听器': 'listener',
    '处理器': 'handler',
    '控制器': 'controller',
    '管理器': 'manager',
    '工厂': 'factory',
    '代理': 'proxy',
    '适配器': 'adapter',
    '装饰器': 'decorator',
    '迭代器': 'iterator',
    '生成器': 'generator',
    '上下文': 'context',
    '环境': 'environment',
    '配置项': 'config item',
    '常量': 'constant',
    '枚举': 'enum',
    '标志': 'flag',
    '状态': 'status',
    '代码': 'code',
    '标识符': 'identifier',
    '版本': 'version',
    '标签': 'tag',
    '分类': 'category',
    '分组': 'group',
    '排序': 'sort order',
    '分页': 'pagination',
    '偏移量': 'offset',
    '限制': 'limit',
    '大小': 'size',
    '长度': 'length',
    '数量': 'count',
    '总数': 'total',
    '页数': 'page count',
    '索引号': 'index number',
    '优先级': 'priority',
    '权重': 'weight',
    '分数': 'score',
    '等级': 'level',
    '状态码': 'status code',
    '错误码': 'error code',
    '消息码': 'message code',
}

def translate_description(chinese_text):
    """Translate Chinese description to English using pattern matching."""
    if not chinese_text or not isinstance(chinese_text, str):
        return ""
    
    # Remove extra whitespace
    text = chinese_text.strip()
    
    # Try to match verb + noun pattern
    words = text
    
    # Replace verbs
    for cn, en in sorted(VERB_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        words = words.replace(cn, en)
    
    # Replace nouns
    for cn, en in sorted(NOUN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        words = words.replace(cn, en)
    
    # Post-processing
    words = words.replace('的', '')
    words = words.replace('一个', 'a ')
    words = words.replace('所有', 'all ')
    words = words.replace('指定', 'specified ')
    words = words.replace('当前', 'current ')
    words = words.replace('新的', 'new ')
    words = words.replace('旧的', 'old ')
    
    # Clean up extra spaces
    words = ' '.join(words.split())
    
    # Capitalize first letter
    if words:
        words = words[0].upper() + words[1:]
    
    return words

def interactive_mode():
    """Run in interactive mode."""
    print("Description Translator (Offline Mode)")
    print("=" * 50)
    print("Enter Chinese descriptions to translate (type 'quit' to exit):")
    print()
    
    while True:
        try:
            user_input = input("> ").strip()
            
            if user_input.lower() in ('quit', 'exit', 'q'):
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            translation = translate_description(user_input)
            
            print(f"Chinese:  {user_input}")
            print(f"English:  {translation}")
            print()
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            break

def batch_mode(texts):
    """Translate multiple descriptions."""
    results = []
    for text in texts:
        results.append({
            'chinese': text,
            'english': translate_description(text)
        })
    return results

def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        # Command line mode
        input_text = ' '.join(sys.argv[1:])
        print(translate_description(input_text))
    else:
        # Interactive mode
        interactive_mode()

if __name__ == '__main__':
    main()