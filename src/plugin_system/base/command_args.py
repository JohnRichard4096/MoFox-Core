"""命令参数解析类

提供简单易用的命令参数解析功能
"""

from typing import List, Optional
import shlex


class CommandArgs:
    """命令参数解析类
    
    提供方便的方法来处理命令参数
    """
    
    def __init__(self, raw_args: str = ""):
        """初始化命令参数
        
        Args:
            raw_args: 原始参数字符串
        """
        self._raw_args = raw_args.strip()
        self._parsed_args: Optional[List[str]] = None
    
    def get_raw(self) -> str:
        """获取完整的参数字符串
        
        Returns:
            str: 原始参数字符串
        """
        return self._raw_args
    
    def get_args(self) -> List[str]:
        """获取解析后的参数列表
        
        将参数按空格分割，支持引号包围的参数
        
        Returns:
            List[str]: 参数列表
        """
        if self._parsed_args is None:
            if not self._raw_args:
                self._parsed_args = []
            else:
                try:
                    # 使用shlex来正确处理引号和转义字符
                    self._parsed_args = shlex.split(self._raw_args)
                except ValueError:
                    # 如果shlex解析失败，fallback到简单的split
                    self._parsed_args = self._raw_args.split()
        
        return self._parsed_args

    @property
    def is_empty(self) -> bool:
        """检查参数是否为空
        
        Returns:
            bool: 如果没有参数返回True
        """
        return len(self.get_args()) == 0
    
    def get_arg(self, index: int, default: str = "") -> str:
        """获取指定索引的参数
        
        Args:
            index: 参数索引（从0开始）
            default: 默认值
            
        Returns:
            str: 参数值或默认值
        """
        args = self.get_args()
        if 0 <= index < len(args):
            return args[index]
        return default

    @property
    def get_first(self, default: str = "") -> str:
        """获取第一个参数
        
        Args:
            default: 默认值
            
        Returns:
            str: 第一个参数或默认值
        """
        return self.get_arg(0, default)
    
    def get_remaining(self, start_index: int = 1) -> str:
        """获取从指定索引开始的剩余参数字符串
        
        Args:
            start_index: 起始索引
            
        Returns:
            str: 剩余参数组成的字符串
        """
        args = self.get_args()
        if start_index < len(args):
            return " ".join(args[start_index:])
        return ""
    
    def count(self) -> int:
        """获取参数数量
        
        Returns:
            int: 参数数量
        """
        return len(self.get_args())
    
    def has_flag(self, flag: str) -> bool:
        """检查是否包含指定的标志参数
        
        Args:
            flag: 标志名（如 "--verbose" 或 "-v"）
            
        Returns:
            bool: 如果包含该标志返回True
        """
        return flag in self.get_args()
    
    def get_flag_value(self, flag: str, default: str = "") -> str:
        """获取标志参数的值
        
        查找 --key=value 或 --key value 形式的参数
        
        Args:
            flag: 标志名（如 "--output"）
            default: 默认值
            
        Returns:
            str: 标志的值或默认值
        """
        args = self.get_args()
        
        # 查找 --key=value 形式
        for arg in args:
            if arg.startswith(f"{flag}="):
                return arg[len(flag) + 1:]
        
        # 查找 --key value 形式
        try:
            flag_index = args.index(flag)
            if flag_index + 1 < len(args):
                return args[flag_index + 1]
        except ValueError:
            pass
        
        return default
    
    def __str__(self) -> str:
        """字符串表示"""
        return self._raw_args
    
    def __repr__(self) -> str:
        """调试表示"""
        return f"CommandArgs(raw='{self._raw_args}', parsed={self.get_args()})"
