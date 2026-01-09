"""
智能图表类型检测器
根据用户问题自动识别需要生成的图表类型
"""
from typing import Dict, List, Tuple, Optional
import re


class ChartTypeDetector:
    """图表类型检测器"""
    
    # 图表类型关键词映射
    CHART_KEYWORDS = {
        'line': ['涨跌', '走势', '趋势', '折线', '曲线', '变化', '波动', '表现', '历史', '时间序列', '趋势图'],
        'candlestick': ['k线', 'k线图', '蜡烛图', '日线', '周线', '月线', '技术分析', '价格走势'],
        'pie': ['占比', '比例', '分布', '份额', '组成', '结构', '饼图', '圆形图', '百分比', '持仓', '成分', '持仓情况', '成分股'],
        'bar': ['对比', '比较', '排名', '柱状图', '条形图', '排行榜', '排序'],
        'tree': ['层级', '树状', '分类', '结构', '组织', '关系', '树形图'],
        'area': ['累计', '累积', '面积', '区域图', '堆叠'],
        'scatter': ['相关性', '散点', '分布', '关系', '关联'],
        'heatmap': ['热力图', '热度', '强度', '密度'],
    }
    
    # 数据维度关键词
    DATA_DIMENSION_KEYWORDS = {
        'price': ['价格', '股价', '收盘价', '开盘价', '最高价', '最低价'],
        'volume': ['成交量', '交易量', '量能', '换手率'],
        'sentiment': ['情绪', '恐慌', '贪婪', '市场情绪', '投资者情绪'],
        'comparison': ['对比', '比较', 'vs', '对比', '相比'],
        'distribution': ['分布', '占比', '比例', '份额'],
    }
    
    @classmethod
    def detect_chart_type(cls, query: str, ticker: Optional[str] = None) -> Dict[str, any]:
        """
        检测用户查询需要的图表类型
        
        Args:
            query: 用户查询
            ticker: 股票代码（可选）
            
        Returns:
            {
                'chart_type': 'line' | 'candlestick' | 'pie' | 'bar' | 'tree' | 'area' | 'scatter' | 'heatmap',
                'data_dimension': 'price' | 'volume' | 'sentiment' | 'comparison' | 'distribution',
                'confidence': float,  # 0-1 置信度
                'reason': str  # 检测原因
            }
        """
        query_lower = query.lower()
        
        # 计算每种图表类型的匹配分数
        scores = {}
        reasons = {}
        
        for chart_type, keywords in cls.CHART_KEYWORDS.items():
            score = 0
            matched_keywords = []
            
            for keyword in keywords:
                if keyword in query_lower:
                    score += 1
                    matched_keywords.append(keyword)
            
            if score > 0:
                scores[chart_type] = score
                reasons[chart_type] = f"匹配关键词: {', '.join(matched_keywords)}"
        
        # 如果没有匹配，使用默认规则
        if not scores:
            # 默认规则：如果包含股票代码，优先使用折线图（适合小白）
            if ticker:
                return {
                    'chart_type': 'line',
                    'data_dimension': 'price',
                    'confidence': 0.5,
                    'reason': '默认使用折线图（适合新手）'
                }
            else:
                return {
                    'chart_type': None,
                    'data_dimension': None,
                    'confidence': 0.0,
                    'reason': '未检测到图表需求'
                }
        
        # 选择得分最高的图表类型
        best_chart_type = max(scores.items(), key=lambda x: x[1])[0]
        confidence = min(scores[best_chart_type] / 3.0, 1.0)  # 归一化到0-1
        
        # 检测数据维度
        data_dimension = cls._detect_data_dimension(query_lower)
        
        return {
            'chart_type': best_chart_type,
            'data_dimension': data_dimension,
            'confidence': confidence,
            'reason': reasons.get(best_chart_type, '')
        }
    
    @classmethod
    def _detect_data_dimension(cls, query: str) -> str:
        """检测数据维度"""
        for dimension, keywords in cls.DATA_DIMENSION_KEYWORDS.items():
            if any(keyword in query for keyword in keywords):
                return dimension
        return 'price'  # 默认价格维度
    
    @classmethod
    def extract_ticker(cls, query: str) -> Optional[str]:
        """从查询中提取股票代码"""
        # 匹配大写字母代码（1-5个字符）
        pattern = r'\b([A-Z]{1,5})\b'
        matches = re.findall(pattern, query)
        
        if matches:
            # 过滤掉常见的非股票代码单词
            common_words = {'THE', 'AND', 'OR', 'FOR', 'TO', 'OF', 'IN', 'ON', 'AT', 'BY'}
            for match in matches:
                if match not in common_words:
                    return match
        
        return None
    
    @classmethod
    def should_generate_chart(cls, query: str) -> bool:
        """判断是否应该生成图表"""
        query_lower = query.lower()
        
        # 图表相关关键词
        chart_indicators = [
            '图表', '图', '走势', '趋势', '涨跌', '表现', '历史',
            '行情', '价格', '股价', '现价', '报价', '市价',
            'k线', '折线', '曲线', '对比', '比较', '占比', '分布',
            '可视化', '展示', '显示', '看看', '查看'
        ]
        
        return any(indicator in query_lower for indicator in chart_indicators)


# 使用示例
if __name__ == "__main__":
    detector = ChartTypeDetector()
    
    test_queries = [
        "AAPL 最近走势如何？",
        "分析一下特斯拉的K线",
        "NVDA 的涨跌情况",
        "苹果和微软的对比",
        "市场情绪分布",
        "各行业占比"
    ]
    
    for query in test_queries:
        result = detector.detect_chart_type(query)
        print(f"查询: {query}")
        print(f"  图表类型: {result['chart_type']}")
        print(f"  数据维度: {result['data_dimension']}")
        print(f"  置信度: {result['confidence']:.2f}")
        print(f"  原因: {result['reason']}")
        print()

