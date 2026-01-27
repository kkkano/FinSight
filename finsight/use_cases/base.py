"""
用例基类 - 定义用例的基本结构
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic
from dataclasses import dataclass

from finsight.domain.models import AnalysisResult


T = TypeVar('T')


class UseCase(ABC, Generic[T]):
    """
    用例基类

    所有用例都应继承此类，实现 execute 方法。
    用例只依赖端口接口，不依赖具体适配器实现。
    """

    @abstractmethod
    def execute(self, *args, **kwargs) -> T:
        """
        执行用例

        Returns:
            T: 用例执行结果
        """
        pass


class AnalysisUseCase(UseCase[AnalysisResult]):
    """
    分析用例基类

    所有分析类用例的基类，返回 AnalysisResult。
    """
    pass
