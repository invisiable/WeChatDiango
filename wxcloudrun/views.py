import json
import logging
import os
import sys
from pathlib import Path

from django.http import JsonResponse
from django.shortcuts import render
from wxcloudrun.models import Counters


logger = logging.getLogger('log')

# 幸运数字预测器路径（内嵌到项目中）
_BASE_DIR = Path(__file__).resolve().parent.parent
LUCKY_PREDICTOR_PATH = str(_BASE_DIR / 'wxcloudrun' / 'predictor')
LUCKY_DATA_PATH = str(_BASE_DIR / 'wxcloudrun' / 'data' / 'lucky_numbers.csv')


def index(request, _):
    """
    获取主页

     `` request `` 请求对象
    """

    return render(request, 'index.html')


def lucky_numbers(request, _=None):
    """
    生成幸运数字 - 基于最优智能投注策略的TOP15预测

    POST body: {"date": "2026-03-05"}  (date仅用于展示，预测始终使用全量数据)
    """
    if request.method != 'POST':
        return JsonResponse({'code': -1, 'errorMsg': '仅支持POST请求'},
                            json_dumps_params={'ensure_ascii': False})

    try:
        # ── 1. 加载数据 ──────────────────────────────────────────────────
        if LUCKY_PREDICTOR_PATH not in sys.path:
            sys.path.insert(0, LUCKY_PREDICTOR_PATH)

        import pandas as pd
        from precise_top15_predictor import PreciseTop15Predictor

        df = pd.read_csv(LUCKY_DATA_PATH, encoding='utf-8-sig')
        total_records = len(df)

        # ── 2. 策略参数（与 GUI _run_optimal_smart_analysis 完全一致）──
        config = {
            'lookback': 12,
            'good_thresh': 0.35,
            'bad_thresh': 0.20,
            'boost_mult': 1.5,
            'reduce_mult': 0.5,
            'max_multiplier': 10,
        }
        fib_sequence = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]

        class SmartDynamic:
            def __init__(self):
                self.fib_index = 0
                self.recent_results = []

            def get_base_mult(self):
                idx = min(self.fib_index, len(fib_sequence) - 1)
                return float(min(fib_sequence[idx], config['max_multiplier']))

            def get_recent_rate(self):
                if not self.recent_results:
                    return 0.33
                return sum(self.recent_results) / len(self.recent_results)

            def process(self, hit):
                """计算本期倍数，然后更新状态（顺序与 GUI process_period 一致）"""
                base_mult = self.get_base_mult()
                if len(self.recent_results) >= config['lookback']:
                    rate = self.get_recent_rate()
                    if rate >= config['good_thresh']:
                        mult = min(base_mult * config['boost_mult'], config['max_multiplier'])
                    elif rate <= config['bad_thresh']:
                        mult = max(base_mult * config['reduce_mult'], 1.0)
                    else:
                        mult = base_mult
                else:
                    mult = base_mult
                # 更新 fib_index（先于 recent_results，与 GUI 一致）
                if hit:
                    self.fib_index = 0
                else:
                    self.fib_index += 1
                self.recent_results.append(1 if hit else 0)
                if len(self.recent_results) > config['lookback']:
                    self.recent_results.pop(0)
                return round(float(mult), 2)

        # ── 3. 回测（与 GUI 完全一致：最近 300 期，调用 update_performance）
        predictor = PreciseTop15Predictor()
        test_periods = min(300, total_records - 50)
        start_idx = total_records - test_periods

        hit_sequence = []
        for i in range(start_idx, total_records):
            train_data = df.iloc[:i]['number'].values
            predictions = predictor.predict(train_data)
            actual = int(df.iloc[i]['number'])
            hit = actual in predictions
            predictor.update_performance(predictions, actual)
            hit_sequence.append(hit)

        # ── 4. 暂停策略模拟（命中1停1期，与 GUI simulate_with_pause 一致）
        pause_strategy = SmartDynamic()
        pause_remaining = 0
        last_result = 'LOSS'
        for hit in hit_sequence:
            if pause_remaining > 0:
                pause_remaining -= 1
                continue  # 暂停期：不投注，不更新策略状态
            pause_strategy.process(hit)
            last_result = 'WIN' if hit else 'LOSS'
            if hit:
                pause_remaining = 1  # 命中后下一期暂停

        # ── 5. 用全量数据（含 update_performance 后的状态）生成下期 TOP15
        all_numbers = df['number'].values
        top15 = predictor.predict(all_numbers)

        # ── 6. 计算下期倍数与星级 ────────────────────────────────────────
        if last_result == 'WIN':
            # 上期命中 → 本期暂停，不投注
            multiplier = 0.0
            stars = 0
        else:
            rate = pause_strategy.get_recent_rate()
            base_mult = pause_strategy.get_base_mult()
            if rate >= config['good_thresh']:
                multiplier = min(base_mult * config['boost_mult'], config['max_multiplier'])
            elif rate <= config['bad_thresh']:
                multiplier = max(base_mult * config['reduce_mult'], 1.0)
            else:
                multiplier = base_mult
            multiplier = round(float(multiplier), 2)
            if multiplier < 2:
                stars = 1
            elif multiplier < 4:
                stars = 2
            elif multiplier < 6:
                stars = 3
            elif multiplier < 8:
                stars = 4
            else:
                stars = 5

        logger.info(f'lucky_numbers: top15={top15}, multiplier={multiplier}, stars={stars}')
        return JsonResponse({
            'code': 0,
            'numbers': top15,
            'multiplier': multiplier,
            'stars': stars,
            'total_records': total_records,
        }, json_dumps_params={'ensure_ascii': False})

    except Exception as e:
        import traceback
        logger.error(f'lucky_numbers error: {traceback.format_exc()}')
        return JsonResponse({'code': -1, 'errorMsg': str(e)},
                            json_dumps_params={'ensure_ascii': False})


def counter(request, _):
    """
    获取当前计数

     `` request `` 请求对象
    """

    rsp = JsonResponse({'code': 0, 'errorMsg': ''}, json_dumps_params={'ensure_ascii': False})
    if request.method == 'GET' or request.method == 'get':
        rsp = get_count()
    elif request.method == 'POST' or request.method == 'post':
        rsp = update_count(request)
    else:
        rsp = JsonResponse({'code': -1, 'errorMsg': '请求方式错误'},
                            json_dumps_params={'ensure_ascii': False})
    logger.info('response result: {}'.format(rsp.content.decode('utf-8')))
    return rsp


def get_count():
    """
    获取当前计数
    """

    try:
        data = Counters.objects.get(id=1)
    except Counters.DoesNotExist:
        return JsonResponse({'code': 0, 'data': 0},
                    json_dumps_params={'ensure_ascii': False})
    return JsonResponse({'code': 0, 'data': data.count},
                        json_dumps_params={'ensure_ascii': False})


def update_count(request):
    """
    更新计数，自增或者清零

    `` request `` 请求对象
    """

    logger.info('update_count req: {}'.format(request.body))

    body_unicode = request.body.decode('utf-8')
    body = json.loads(body_unicode)

    if 'action' not in body:
        return JsonResponse({'code': -1, 'errorMsg': '缺少action参数'},
                            json_dumps_params={'ensure_ascii': False})

    if body['action'] == 'inc':
        try:
            data = Counters.objects.get(id=1)
        except Counters.DoesNotExist:
            data = Counters()
        data.id = 1
        data.count += 1
        data.save()
        return JsonResponse({'code': 0, "data": data.count},
                    json_dumps_params={'ensure_ascii': False})
    elif body['action'] == 'clear':
        try:
            data = Counters.objects.get(id=1)
            data.delete()
        except Counters.DoesNotExist:
            logger.info('record not exist')
        return JsonResponse({'code': 0, 'data': 0},
                    json_dumps_params={'ensure_ascii': False})
    else:
        return JsonResponse({'code': -1, 'errorMsg': 'action参数错误'},
                    json_dumps_params={'ensure_ascii': False})
