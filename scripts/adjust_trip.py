"""
adjust_trip.py — 出差区间中断返程检测与拆分

根据高铁票/大巴票日期检测出差中途返程，将原始区间拆分为子区间，
使得补贴计算（compute_daily_subsidy）自然处理 50% 首末日规则。

用法:
    from adjust_trip import process_trip_interruptions
    sub_trips, questions = process_trip_interruptions(trips, train_fares, bus_fares, didi_trip, base_didi)
"""
from datetime import date, timedelta


def split_trip_by_expenses(trip, train_fares, bus_fares, didi_trip, base_didi):
    """分析单个出差区间，根据费用日期检测中断并拆分子区间。

    Args:
        trip: dict {start, end, from_city, to_city, reason, ...}
        train_fares: {date: amount} or {date: dict}
        bus_fares: {date: amount} or {date: dict}
        didi_trip: {date: amount}  出差地滴滴
        base_didi: {date: amount}  Base地滴滴

    Returns:
        (sub_trips, questions)
        sub_trips: list[dict]，拆分子区间（无中断时返回 [trip]）
        questions: list[dict]，需要用户确认的问题
    """
    from utils import norm_city
    start, end = trip['start'], trip['end']
    base_city = trip.get('from_city', '广州')
    dest_city = trip.get('to_city', '深圳')

    # ── 收集中断日期（高铁/大巴票，非首末日）──
    fare_dates = set()
    ticket_details = {}  # 存放带方向信息的富票据

    for fares_dict in (train_fares, bus_fares):
        if not fares_dict:
            continue
        for d, val in fares_dict.items():
            if start < d < end:
                if isinstance(val, (int, float)) and val > 0:
                    fare_dates.add(d)
                elif isinstance(val, dict) and val.get('amount', 0) > 0:
                    fare_dates.add(d)
                    ticket_details[d] = val

    # ── 区间末费用检测：最后一条费用作为中断信号 ──
    all_expense_dates = set(fare_dates)
    for d in (didi_trip or {}):
        if start < d < end:
            all_expense_dates.add(d)
    for d in (base_didi or {}):
        if start < d < end:
            all_expense_dates.add(d)
    if all_expense_dates:
        last_d = max(all_expense_dates)
        if last_d not in fare_dates:
            fare_dates.add(last_d)
            print(f"    [末费用] {last_d} 为区间末费用，触发中断检测")

    if not fare_dates:
        return [trip], []

    sorted_dates = sorted(fare_dates)
    n = len(sorted_dates)
    labels = [None] * n

    norm_base = norm_city(base_city)

    # ── 1. 尝试使用方向和费用来判定票据属性 ──
    for i, d in enumerate(sorted_dates):
        # 1.1 优先通过车票自身的出发/目的城市判定
        if d in ticket_details:
            detail = ticket_details[d]
            fc = detail.get('from_city')
            tc = detail.get('to_city')
            if fc and tc:
                if norm_city(tc) == norm_base:
                    labels[i] = 'RETURN'
                elif norm_city(fc) == norm_base:
                    labels[i] = 'DEPARTURE'

        if labels[i] is not None:
            continue

        # 1.2 检查在 window [d + 1, next_d - 1] (or end) 内的滴滴活跃度
        next_d = sorted_dates[i+1] if i + 1 < n else None
        window_end = next_d - timedelta(days=1) if next_d else end
        
        curr = d + timedelta(days=1)
        trip_active = False
        base_active = False
        while curr <= window_end:
            if curr in (didi_trip or {}):
                trip_active = True
            if curr in (base_didi or {}):
                base_active = True
            curr += timedelta(days=1)

        if trip_active and not base_active:
            labels[i] = 'DEPARTURE'
        elif base_active and not trip_active:
            labels[i] = 'RETURN'

    # ── 2. 状态传播约束求解（交替传播补全 None）──
    changed = True
    while changed:
        changed = False
        for i in range(n):
            if labels[i] is not None:
                if i > 0 and labels[i-1] is None:
                    labels[i-1] = 'DEPARTURE' if labels[i] == 'RETURN' else 'RETURN'
                    changed = True
                if i < n - 1 and labels[i+1] is None:
                    labels[i+1] = 'DEPARTURE' if labels[i] == 'RETURN' else 'RETURN'
                    changed = True

    # ── 3. 兜底交替打标（若仍有 None 盲区，如无任何费用活动）──
    for i in range(n):
        if labels[i] is None:
            if i == 0:
                labels[i] = 'RETURN'
            else:
                labels[i] = 'DEPARTURE' if labels[i-1] == 'RETURN' else 'RETURN'

    # ── 4. 根据标签重构子区间 ──
    sub_trips = []
    questions = []
    seg_start = start

    for d, lbl in zip(sorted_dates, labels):
        if lbl == 'RETURN':
            if seg_start is not None:
                sub = dict(trip)
                sub['start'] = seg_start
                sub['end'] = d
                sub_trips.append(sub)
            seg_start = None
        elif lbl == 'DEPARTURE':
            seg_start = d

    # ── 5. 处理最末端中断后的剩余天数 ──
    if seg_start is not None:
        if seg_start < end:
            sub = dict(trip)
            sub['start'] = seg_start
            sub['end'] = end
            sub_trips.append(sub)
    else:
        # 最末尾是 RETURN，检查此后是否有费用以决定是否提前结束
        last_return = sorted_dates[-1]
        has_after = _has_expenses_after(last_return, end, sorted_dates, didi_trip, base_didi)

        if not has_after:
            questions.append({
                'type': 'early_end',
                'trip': trip,
                'last_return': last_return,
                'sub_trips_built': list(sub_trips),
            })
        else:
            sub = dict(trip)
            sub['start'] = last_return + timedelta(days=1)
            sub['end'] = end
            sub_trips.append(sub)

    return sub_trips, questions


def _has_expenses_after(pivot_date, trip_end, fare_dates, didi_trip, base_didi):
    for d in fare_dates:
        if d > pivot_date:
            return True
    if didi_trip:
        for d in didi_trip:
            if pivot_date < d <= trip_end:
                return True
    if base_didi:
        for d in base_didi:
            if pivot_date < d <= trip_end:
                return True
    return False


def process_trip_interruptions(merged_trips, train_fares, bus_fares, didi_trip, base_didi):
    """批量处理所有合并区间的中断检测。"""
    all_sub_trips = []
    all_questions = []

    for trip in (merged_trips or []):
        sub_trips, questions = split_trip_by_expenses(
            trip, train_fares, bus_fares, didi_trip, base_didi
        )
        all_sub_trips.extend(sub_trips)
        all_questions.extend(questions)

    return all_sub_trips, all_questions


def apply_answer(questions, answers):
    """应用用户的回答到待确认问题，返回调整后的 sub_trips。

    Args:
        questions: list[dict]，process_trip_interruptions 返回的问题列表
        answers: list[bool]，对应每个问题的回答（True=提前结束, False=继续）

    Returns:
        list[dict]：包含用户确认后补充的 sub_trips
    """
    extra = []
    for q, ans in zip(questions, answers):
        if q['type'] == 'early_end' and ans:
            # 用户回答「是」（提前结束）→ process_trip_interruptions 返回的 trips 中已包含 sub_trips_built，无需补充
            pass
        elif q['type'] == 'early_end' and not ans:
            # 用户回答「否」（没有提前结束）→ 延伸到最后
            sub = dict(q['trip'])
            sub['start'] = q['last_return'] + timedelta(days=1)
            sub['end'] = q['trip']['end']
            extra.append(sub)
    return extra
