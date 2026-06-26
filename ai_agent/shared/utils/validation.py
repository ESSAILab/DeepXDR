import socket
from typing import Tuple


def is_valid_ipv4(ip: str) -> bool:
    """验证IPv4地址是否有效"""
    try:
        # 使用socket库进行验证
        socket.inet_aton(ip)
        # 进一步验证格式是否正确
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        for part in parts:
            if not part.isdigit():
                return False
            num = int(part)
            if num < 0 or num > 255:
                return False
            # 检查是否有前导0，除非是0本身
            if len(part) > 1 and part.startswith('0'):
                return False
        return True
    except socket.error:
        return False


def is_valid_ipv6(ip: str) -> bool:
    """验证IPv6地址是否有效"""
    try:
        socket.inet_pton(socket.AF_INET6, ip)
        return True
    except socket.error:
        return False


def validate_ip_with_reason(ip: str) -> Tuple[bool, str]:
    """
    验证IP地址并返回详细原因
    返回 (是否有效, 原因)
    """
    if not ip or not isinstance(ip, str):
        return False, "IP地址不能为空"
    
    ip = ip.strip()
    if not ip:
        return False, "IP地址不能为空"
    
    # 检查IPv4
    if '.' in ip and is_valid_ipv4(ip):
        return True, "有效的IPv4地址"
    
    # 检查IPv6
    if ':' in ip and is_valid_ipv6(ip):
        return True, "有效的IPv6地址"
    
    # 常见错误类型分析
    if ip.count('.') != 3 and '.' in ip:
        return False, "IPv4地址格式错误：应该包含3个点"
    
    if ip.count(':') == 0 and '.' not in ip:
        return False, "IP地址格式错误：既不是有效的IPv4也不是IPv6格式"
    
    parts = ip.split('.') if '.' in ip else []
    if parts:
        for i, part in enumerate(parts):
            if not part.isdigit():
                return False, f"IPv4地址第{i+1}部分不是数字：{part}"
            num = int(part)
            if num < 0 or num > 255:
                return False, f"IPv4地址第{i+1}部分超出范围[0-255]：{num}"
    
    return False, "无效的IP地址格式"

