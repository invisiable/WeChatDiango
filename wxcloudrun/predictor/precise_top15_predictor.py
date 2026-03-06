"""
TOP15精准版预测器 - 专注提高命中质量降低连续不中
策略：不增加号码数量，而是提高15个号码的准确度
"""

import numpy as np
import pandas as pd
from collections import Counter
from top15_predictor import Top15Predictor


class PreciseTop15Predictor(Top15Predictor):
    """精准版TOP15预测器 - 继承原版并优化"""
    
    def __init__(self):
        super().__init__()
        self.consecutive_misses = 0
        self.recent_predictions = []  # 保存最近的预测
        self.recent_actuals = []  # 保存最近的实际结果
    
    def update_performance(self, prediction, actual):
        """更新性能追踪"""
        hit = actual in prediction
        
        if hit:
            self.consecutive_misses = 0
        else:
            self.consecutive_misses += 1
        
        # 保留最近20期
        self.recent_predictions.append(prediction)
        self.recent_actuals.append(actual)
        
        if len(self.recent_predictions) > 20:
            self.recent_predictions.pop(0)
            self.recent_actuals.pop(0)
    
    def method_precision_frequency(self, pattern, k=20):
        """精准频率方法 - 提高质量"""
        recent_30 = pattern['recent_30']
        recent_10 = pattern['recent_10']
        recent_5 = pattern['recent_5']
        freq_30 = Counter(recent_30)
        freq_10 = Counter(recent_10)
        
        weighted = {}
        for n in range(1, 50):
            weight = 0.5  # 基础权重
            
            # 多时间窗口频率融合
            freq_30_score = freq_30.get(n, 0)
            freq_10_score = freq_10.get(n, 0)
            
            # 30期频率（长期趋势）
            if freq_30_score > 0:
                weight += freq_30_score * 0.3
            
            # 10期频率（短期趋势，权重更高）
            if freq_10_score > 0:
                weight += freq_10_score * 0.6
            
            # 最近5期出现过的显著降权
            if n in recent_5:
                weight *= 0.2
            
            # 极端值趋势分析
            if pattern['is_extreme']:
                if n <= 10 or n >= 40:
                    weight *= 2.0
                else:
                    weight *= 0.4
            else:
                # 非极端趋势，偏好中间值
                if 15 <= n <= 35:
                    weight *= 1.5
            
            weighted[n] = weight
        
        sorted_nums = sorted(weighted.items(), key=lambda x: x[1], reverse=True)
        return [num for num, _ in sorted_nums[:k]]
    
    def method_avoid_recent_misses(self, pattern, k=20):
        """避免最近频繁未中的号码"""
        recent_30 = pattern['recent_30']
        freq = Counter(recent_30)
        
        # 统计最近哪些号码被预测但未中
        missed_numbers = Counter()
        if self.recent_predictions:
            for pred, actual in zip(self.recent_predictions, self.recent_actuals):
                for n in pred:
                    if n != actual:
                        missed_numbers[n] += 1
        
        weighted = {}
        for n in range(1, 50):
            weight = 1.0
            
            # 基础频率
            if freq.get(n, 0) > 0:
                weight += freq[n] * 0.3
            
            # 惩罚频繁预测错误的号码
            if n in missed_numbers:
                miss_count = missed_numbers[n]
                weight *= (1.0 / (1 + miss_count * 0.3))
            
            # 最近5期出现过的降权
            if n in pattern['recent_5']:
                weight *= 0.3
            
            weighted[n] = weight
        
        sorted_nums = sorted(weighted.items(), key=lambda x: x[1], reverse=True)
        return [num for num, _ in sorted_nums[:k]]
    
    def method_gap_analysis(self, pattern, k=20):
        """间隔分析 - 精准版"""
        recent_50 = pattern['recent_50'] if 'recent_50' in pattern else pattern['recent_30']
        
        # 计算每个号码的间隔
        last_appearance = {}
        for i, n in enumerate(recent_50):
            last_appearance[n] = i
        
        current_pos = len(recent_50)
        weighted = {}
        
        for n in range(1, 50):
            if n in last_appearance:
                gap = current_pos - last_appearance[n]
                # 间隔在5-15期之间的号码优先
                if 5 <= gap <= 15:
                    weight = 2.0
                elif 15 < gap <= 25:
                    weight = 1.5
                elif gap > 25:
                    weight = 1.2
                else:  # gap < 5
                    weight = 0.5
            else:
                # 从未出现的号码适度考虑
                weight = 1.0
            
            # 避开最近5期
            if n in pattern['recent_5']:
                weight *= 0.2
            
            weighted[n] = weight
        
        sorted_nums = sorted(weighted.items(), key=lambda x: x[1], reverse=True)
        return [num for num, _ in sorted_nums[:k]]
    
    def predict(self, numbers):
        """精准预测 - 始终返回15个高质量号码"""
        pattern = self.analyze_pattern(numbers)
        
        # 添加recent_50支持
        if len(numbers) >= 50:
            pattern['recent_50'] = numbers[-50:]
        else:
            pattern['recent_50'] = numbers
        
        # 运行多个方法，权重调整
        base_k = 22
        methods = [
            (self.method_precision_frequency(pattern, base_k), 0.40),  # 最高权重
            (self.method_zone_dynamic(pattern, base_k), 0.25),
            (self.method_gap_analysis(pattern, base_k), 0.20),
            (self.method_avoid_recent_misses(pattern, base_k), 0.15)
        ]
        
        # 综合评分
        scores = {}
        for candidates, weight in methods:
            for rank, num in enumerate(candidates):
                score = weight * (1.0 - rank / len(candidates))
                scores[num] = scores.get(num, 0) + score
        
        # 始终返回15个号码
        final = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [num for num, _ in final[:15]]
    
    def get_analysis(self, numbers):
        """获取详细分析"""
        pattern = self.analyze_pattern(numbers)
        prediction = self.predict(numbers)
        
        # 分析预测结果
        zones = {
            '极小值区(1-10)': [n for n in prediction if 1 <= n <= 10],
            '小值区(11-20)': [n for n in prediction if 11 <= n <= 20],
            '中值区(21-30)': [n for n in prediction if 21 <= n <= 30],
            '大值区(31-40)': [n for n in prediction if 31 <= n <= 40],
            '极大值区(41-49)': [n for n in prediction if 41 <= n <= 49]
        }
        
        elements = {'金': [], '木': [], '水': [], '火': [], '土': []}
        for n in prediction:
            for element, nums in self.element_numbers.items():
                if n in nums:
                    elements[element].append(n)
                    break
        
        return {
            'top15': prediction,
            'trend': '极端值趋势' if pattern['is_extreme'] else '正常趋势',
            'extreme_ratio': pattern['extreme_ratio'] * 100,
            'zones': zones,
            'elements': {k: v for k, v in elements.items() if v},
            'consecutive_misses': self.consecutive_misses
        }


def main():
    """测试"""
    print("=" * 80)
    print("精准版 Top 15 预测器")
    print("=" * 80)
    
    # 读取数据
    df = pd.read_csv('data/lucky_numbers.csv', encoding='utf-8-sig')
    numbers = df['number'].values
    
    print(f"\n基于历史数据: {len(df)}期")
    print(f"最近10期: {numbers[-10:].tolist()}")
    
    # 创建预测器
    predictor = PreciseTop15Predictor()
    
    # 获取分析
    analysis = predictor.get_analysis(numbers)
    
    print(f"\n🎯 下一期预测（精准15个）:")
    print(f"  {analysis['top15']}")
    
    print("\n✅ 预测完成")


if __name__ == '__main__':
    main()
