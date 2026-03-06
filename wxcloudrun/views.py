import json
import logging
import os
import sys

from django.http import JsonResponse
from django.shortcuts import render
from wxcloudrun.models import Counters


logger = logging.getLogger('log')

# 幸运数字预测器路径
LUCKY_PREDICTOR_PATH = r'C:\Project\liuhe'
LUCKY_DATA_PATH = os.path.join(LUCKY_PREDICTOR_PATH, 'data', 'lucky_numbers.csv')


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
        body = {}
        if request.body:
            body = json.loads(request.body.decode('utf-8'))
        selected_date = body.get('date', '')

        # ── 1. 注入预测器路径并加载数据 ──────────────────────────────────
        if LUCKY_PREDICTOR_PATH not in sys.path:
            sys.path.insert(0, LUCKY_PREDICTOR_PATH)

        import pandas as pd
        import numpy as np
        from precise_top15_predictor import PreciseTop15Predictor

        df = pd.read_csv(LUCKY_DATA_PATH, encoding='utf-8-sig')
        numbers = df['number'].values
        total_records = len(numbers)

        # ── 2. 预测TOP15 ────────────────────────────────────────────────
        predictor = PreciseTop15Predictor()
        top15 = predictor.predict(numbers)

        # ── 3. 计算当前SmartDynamic倍数（最优智能动态倍投 v3.1 参数）──
        #   config同 lucky_number_gui.py 中 _run_optimal_smart_analysis()
        config = {
            'lookback': 12,
            'good_thresh': 0.35,
            'bad_thresh': 0.20,
            'boost_mult': 1.5,
            'reduce_mult': 0.5,
            'max_multiplier': 10,
        }
        fib_sequence = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]

        # 从最新一期往前扫描确定 fib_index（命中即停）
        fib_index = 0
        for i in range(total_records - 1, max(total_records - 50, -1), -1):
            period_numbers = numbers[:i]
            if len(period_numbers) < 15:
                break
            pred = predictor.predict(period_numbers)
            actual = numbers[i]
            if actual in pred:
                break  # 命中，fib_index已是正确值（连续未中次数）
            fib_index += 1
            if fib_index >= len(fib_sequence) - 1:
                break

        # 统计最近lookback期命中率
        lookback = config['lookback']
        recent_hits = 0
        eval_start = max(total_records - lookback, 1)
        for i in range(eval_start, total_records):
            period_numbers = numbers[:i]
            if len(period_numbers) < 15:
                continue
            pred_check = predictor.predict(period_numbers)
            if numbers[i] in pred_check:
                recent_hits += 1
        recent_sample = total_records - eval_start
        recent_hit_rate = recent_hits / recent_sample if recent_sample > 0 else 0.33

        # 基础倍数（斐波那契）
        base_mult = float(min(fib_sequence[min(fib_index, len(fib_sequence) - 1)],
                              config['max_multiplier']))

        # 动态调整
        if recent_hit_rate >= config['good_thresh']:
            multiplier = min(base_mult * config['boost_mult'], config['max_multiplier'])
        elif recent_hit_rate <= config['bad_thresh']:
            multiplier = max(base_mult * config['reduce_mult'], 1.0)
        else:
            multiplier = base_mult
        multiplier = round(float(multiplier), 2)

        # ── 4. 倍数映射星级（1x-2x→1星 … 8x-10x→5星）─────────────────
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
            'selected_date': selected_date,
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
