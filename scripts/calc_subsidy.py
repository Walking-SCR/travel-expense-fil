"""
calc_subsidy.py — 差旅补贴计算

用法:
    from calc_subsidy import compute_daily_subsidy, collect_overtime_dates

    ot = collect_overtime_dates(merged_trips)
    days = compute_daily_subsidy(merged_trips, overtime_dates=ot)

    返回: list[(date, {"subsidy": float, "from_city": str, "to_city": str, "reason": str, "standard": int})]
"""
from datetime import date, timedelta
from collections import defaultdict

# ── 城市分类 ──
TIER1 = {"北京", "上海", "广州", "深圳", "香港"}
TIER2 = {
    "澳门", "厦门", "珠海", "天津", "重庆", "青岛", "苏州",
    "武汉", "成都", "杭州", "南京", "西安", "郑州", "长沙",
    "济南", "福州", "合肥", "昆明", "沈阳", "哈尔滨",
    "长春", "南昌", "太原", "石家庄", "贵阳", "南宁", "兰州",
    "海口", "银川", "西宁", "拉萨", "乌鲁木齐", "呼和浩特",
}

# ── 补贴标准表 ──
# STANDARDS[std][tier] = daily_amount
# std=1: 标准一（公司订酒店）  std=2: 标准二（自行解决）
STANDARDS = {
    1: {1: 60,  2: 50,  3: 40},
    2: {1: 220, 2: 180, 3: 145},
}


def _get_tier(c):
    """城市 → 分类等级（1/2/3）"""
    if not c:
        return 3
    from utils import norm_city
    cn = norm_city(c)
    if cn in TIER1:
        return 1
    if cn in TIER2:
        return 2
    # 模糊子串匹配：支持 "深圳南站" -> "深圳" (Tier 1) 或 "广州白云" -> "广州" (Tier 1)
    for city in TIER1:
        if city in cn or (len(cn) >= 2 and cn in city):
            return 1
    for city in TIER2:
        if city in cn or (len(cn) >= 2 and cn in city):
            return 2
    return 3


def _get_base(std, tier):
    """标准+等级 → 每日补贴金额"""
    return STANDARDS[std][tier]


def _daily_subsidy(d, start, end, tier, std, overtime_dates):
    """
    计算单日补贴。

    - 出发日 / 结束日：标准 × 50%
    - 中间工作日：标准 × 100%
    - 中间周末（无加班）：标准 × 50%
    - 中间周末（有加班）：标准 × 100%
    """
    base = _get_base(std, tier)

    if d in overtime_dates:
        return base  # 有加班：100%

    if d == start or d == end:
        return round(base * 0.5, 2)

    if d.weekday() in (5, 6):  # 周六/周日
        return round(base * 0.5, 2)  # 无加班：50%

    return base  # 工作日：100%


def collect_overtime_dates(merged_trips):
    """
    收集出差区间内所有周末日期（加班会影响补贴）。

    仅收集周六/周日。工作日出发/结束日不需要加班确认——
    无加班时已按 50% 计算，有加班才会影响。

    如果区间不涉及周六、日，返回空 set，调用方应跳过加班询问。
    """
    overtime = set()
    for t in merged_trips:
        cur = t["start"]
        while cur <= t["end"]:
            if cur.weekday() in (5, 6):
                overtime.add(cur)
            cur += timedelta(days=1)
    return overtime


def has_weekends_in_trips(merged_trips):
    """判断出差区间是否包含周末。返回 True 表示有周末。"""
    for t in merged_trips:
        cur = t["start"]
        while cur <= t["end"]:
            if cur.weekday() in (5, 6):
                return True
            cur += timedelta(days=1)
    return False


def parse_overtime_reply(reply_text, year=2026):
    """
    解析用户回复的加班日期。
    支持格式：「12/6、12/7 有加班」「12/6-12/8加班」「12/6 12/7」
    """
    import re
    dates = set()

    # 格式1：12/6-12/7 或 12/6~12/7
    ranges = re.findall(r'(\d{1,2})[/\-](\d{1,2})\s*[~\-至到]\s*(\d{1,2})[/\-](\d{1,2})', reply_text)
    for r in ranges:
        # 假设同一月
        m1, d1, m2, d2 = int(r[0]), int(r[1]), int(r[2]), int(r[3])
        # 如果 m1 != m2 需要另外处理，这里简化：取 m1
        for d in range(d1, d2 + 1):
            try:
                dates.add(date(year, m1, d))
            except ValueError:
                pass

    # 格式2：12/6, 12/7 等散列
    singles = re.findall(r'(\d{1,2})[/\-](\d{1,2})', reply_text)
    for s in singles:
        m, d = int(s[0]), int(s[1])
        try:
            dates.add(date(year, m, d))
        except ValueError:
            pass

    return dates


def compute_daily_subsidy(merged_trips, overtime_dates=None, year=2025):
    """
    计算每日补贴序列。

    每个合并区间独立计算，同一天多区间取补贴最大者。
    overtime_dates: set of date，已确认有加班的日期（None 表示无加班，全部50%）
    """
    if overtime_dates is None:
        overtime_dates = set()

    from utils import norm_city

    day_map = {}  # {date: info}

    for t in merged_trips:
        # 目的城市取第一个（用于计算等级）
        primary_city = norm_city(t["to_city"].split("；")[0])
        tier = _get_tier(primary_city)
        std = t.get("standard", 2)  # 默认标准二
        s, e = t["start"], t["end"]

        cur = s
        while cur <= e:
            sub = _daily_subsidy(cur, s, e, tier, std, overtime_dates)

            if cur not in day_map or sub > day_map[cur]["subsidy"]:
                day_map[cur] = {
                    "subsidy": sub,
                    "from_city": t["from_city"],
                    "to_city": t["to_city"],
                    "reason": t["reason"],
                    "standard": std,
                }
            elif sub == day_map[cur]["subsidy"]:
                # 理由合并（去重）
                reasons = day_map[cur]["reason"]
                if t["reason"] and t["reason"] not in reasons:
                    reasons += "；" + t["reason"]
                day_map[cur]["reason"] = reasons

            cur += timedelta(days=1)

    days = sorted(day_map.items())
    return days
