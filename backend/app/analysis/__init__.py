"""标的分析聚合：把行情、指标、关键价位、相关系数与关联回测组装成一份只读视图。

本模块只做编排与纯计算，不承载 HTTP 契约；接口层只负责把这里的值对象转换成响应
模型。跨包调用一律走各域门面。
"""

from app.analysis.service import (
    ANALYSIS_BARS,
    Analysis,
    AnalysisCandles,
    PricePoint,
    instrument_analysis,
)

__all__ = ["ANALYSIS_BARS", "Analysis", "AnalysisCandles", "PricePoint", "instrument_analysis"]
