import json
import logging
import os
import sys
from pathlib import Path

from django.http import JsonResponse
from django.shortcuts import render
from wxcloudrun.models import Counters


logger = logging.getLogger('log')

ADMIN_PASSWORD = '8888'

# 幸运数字预测器路径（内嵌到项目中）
_BASE_DIR = Path(__file__).resolve().parent.parent
LUCKY_PREDICTOR_PATH = str(_BASE_DIR / 'wxcloudrun' / 'predictor')
LUCKY_DATA_PATH = str(_BASE_DIR / 'wxcloudrun' / 'data' / 'lucky_numbers.csv')


def index(request, _):
    """获取主页"""
    return render(request, 'index.html')


def record_page(request, _=None):
    """录入中奖号码页面"""
    return render(request, 'record.html')


def record_api(request, _=None):
    """中奖号码录入 API：GET 返回最近记录，POST 写入新记录"""
    if request.method == 'GET':
        try:
            import pandas as pd
            df = pd.read_csv(LUCKY_DATA_PATH, encoding='utf-8-sig')
            if len(df) == 0:
                return JsonResponse({'code': 0, 'last': None, 'total': 0},
                                    json_dumps_params={'ensure_ascii': False})
            last = df.iloc[-1]
            return JsonResponse({
                'code': 0,
                'last': {
                    'date': str(last['date']),
                    'number': int(last['number']),
                    'animal': str(last['animal']),
                    'element': str(last['element']),
                },
                'total': len(df),
            }, json_dumps_params={'ensure_ascii': False})
        except Exception as e:
            return JsonResponse({'code': -1, 'errorMsg': str(e)},
                                json_dumps_params={'ensure_ascii': False})

    elif request.method == 'POST':
        try:
            body = json.loads(request.body.decode('utf-8'))

            # ── 密码验证 ──────────────────────────────────────────────────
            if body.get('password') != ADMIN_PASSWORD:
                return JsonResponse({'code': 401, 'errorMsg': '密码错误'},
                                    json_dumps_params={'ensure_ascii': False})

            date_str = str(body.get('date', '')).strip()
            number = body.get('number')
            animal = str(body.get('animal', '')).strip()
            element = str(body.get('element', '')).strip()

            valid_animals = ['鼠', '牛', '虎', '兔', '龙', '蛇', '马', '羊', '猴', '鸡', '狗', '猪']
            valid_elements = ['金', '木', '水', '火', '土']

            if not date_str:
                return JsonResponse({'code': -1, 'errorMsg': '日期不能为空'},
                                    json_dumps_params={'ensure_ascii': False})

            # 将 HTML date input 的 YYYY-MM-DD 转为 YYYY/M/D
            from datetime import datetime as _dt
            try:
                d = _dt.strptime(date_str, '%Y-%m-%d')
                formatted_date = f"{d.year}/{d.month}/{d.day}"
            except ValueError:
                return JsonResponse({'code': -1, 'errorMsg': '日期格式错误，请使用 YYYY-MM-DD'},
                                    json_dumps_params={'ensure_ascii': False})

            try:
                number = int(number)
                if not (1 <= number <= 49):
                    raise ValueError()
            except (ValueError, TypeError):
                return JsonResponse({'code': -1, 'errorMsg': '号码必须在 1–49 之间'},
                                    json_dumps_params={'ensure_ascii': False})

            if animal not in valid_animals:
                return JsonResponse({'code': -1, 'errorMsg': f'生肖无效: {animal}'},
                                    json_dumps_params={'ensure_ascii': False})
            if element not in valid_elements:
                return JsonResponse({'code': -1, 'errorMsg': f'五行无效: {element}'},
                                    json_dumps_params={'ensure_ascii': False})

            import csv
            # 确保文件末尾有换行符，防止新行粘连到上一行
            with open(LUCKY_DATA_PATH, 'rb+') as f:
                f.seek(0, 2)  # 移到文件末尾
                if f.tell() > 0:
                    f.seek(-1, 2)
                    last_byte = f.read(1)
                    if last_byte not in (b'\n', b'\r'):
                        f.write(b'\n')
            with open(LUCKY_DATA_PATH, 'a', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([formatted_date, number, animal, element])

            logger.info(f'record saved: {formatted_date},{number},{animal},{element}')
            return JsonResponse({
                'code': 0,
                'message': f'保存成功：{formatted_date}  {number}号  {animal}  {element}',
            }, json_dumps_params={'ensure_ascii': False})

        except Exception as e:
            import traceback
            logger.error(f'record_api error: {traceback.format_exc()}')
            return JsonResponse({'code': -1, 'errorMsg': str(e)},
                                json_dumps_params={'ensure_ascii': False})

    return JsonResponse({'code': -1, 'errorMsg': '方法不支持'},
                        json_dumps_params={'ensure_ascii': False})


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
