"""
parse_trip.py — 携程商旅 PDF 解析 + 多区间合并

用法:
    from parse_trip import parse_all_ctrip
    merged = parse_all_ctrip(pdf_paths, default_year=2025)

返回: list[dict]，每个 dict 含:
    start, end (date), from_city, to_city, reason, pdf_path
"""
import sys, fitz, re
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import norm_city


def parse_one_ctrip(pdf_path, default_year=2025):
    """
    解析单个携程 PDF，返回 dict（日期为 None 表示解析失败）。

    ⚠️ PDF 中「目的城市」和「深圳」分行，一次 re 无法跨行匹配，
    必须用 r'目的城市\s*\n([^\n]+)' 先行定位再取下一行。
    """
    doc = fitz.open(str(pdf_path))
    text = doc[0].get_text()
    doc.close()

    # 尝试多种日期格式
    patterns = [
        r'开始日期\s+(\d+)/(\d+)/(\d+)',
        r'出发日期\s+(\d+)/(\d+)/(\d+)',
    ]
    sm = None
    for pat in patterns:
        sm = re.search(pat, text)
        if sm:
            # 判断年份在哪个位置
            g1, g2, g3 = sm.group(1), sm.group(2), sm.group(3)
            if int(g1) > 12:  # 年/月/日
                yr, mo, dy = int(g1), int(g2), int(g3)
            elif int(g3) > 12:  # 月/日/年
                yr, mo, dy = int(g3), int(g1), int(g2)
            else:  # 可能是 日/月/年（少见）
                yr, mo, dy = default_year, int(g1), int(g2)
            start_date = date(yr, mo, dy)
            break

    em = re.search(r'结束日期\s+(\d+)/(\d+)/(\d+)', text)
    if em:
        g1, g2, g3 = em.group(1), em.group(2), em.group(3)
        if int(g1) > 12:
            yr, mo, dy = int(g1), int(g2), int(g3)
        elif int(g3) > 12:
            yr, mo, dy = int(g3), int(g1), int(g2)
        else:
            yr, mo, dy = default_year, int(g1), int(g2)
        end_date = date(yr, mo, dy)
    else:
        end_date = None

    # 出差事由
    rm = re.search(r'出差事由\s+([^\n]+)', text)
    reason = rm.group(1).strip() if rm else ""

    # 出发/目的城市（分行模式：先定位关键词，再取下一行）
    scm = re.search(r'出发城市\s*\n([^\n]+)', text)
    from_city = scm.group(1).strip() if scm else ""
    dcm = re.search(r'目的城市\s*\n([^\n]+)', text)
    to_city = dcm.group(1).strip() if dcm else ""
    # 备选：同行模式（极少数情况）
    if not to_city:
        tmp = re.search(r'出发城市\s+([^\n]+).*?目的城市\s+([^\n]+)', text, re.DOTALL)
        if tmp:
            from_city = tmp.group(1).strip()
            to_city = tmp.group(2).strip()

    result = {
        "start": start_date,
        "end": end_date,
        "from_city": from_city,
        "to_city": to_city,
        "reason": reason,
        "pdf_path": str(pdf_path),
    }
    print(f"  [携程] {start_date} ~ {end_date} {from_city}→{to_city} | {reason}")
    return result


def merge_intervals(trips):
    """
    多区间合并：按开始日期排序，合并重叠或相邻（间隔≤1天）的区间。
    返回新的 merged list（就地修改传入列表的副本）。
    """
    if not trips:
        return []

    sorted_trips = sorted([t for t in trips if t["start"] and t["end"]], key=lambda x: x["start"])

    merged = []
    for t in sorted_trips:
        if not merged:
            merged.append(t)
        else:
            last = merged[-1]
            # 相邻（间隔≤1天）或重叠
            if t["start"] <= last["end"] + timedelta(days=1):
                # 合并到上一个区间
                last["end"] = max(last["end"], t["end"])
                last["reason"] = last["reason"] + "；" + t["reason"]
                last["to_city"] = last["to_city"] + "；" + t["to_city"]
            else:
                merged.append(t)

    return merged


def parse_all_ctrip(pdf_paths, default_year=2025):
    """
    主入口：解析所有携程 PDF 并合并区间。
    pdf_paths: list of Path 或 str
    """
    trips = []
    for p in pdf_paths:
        try:
            t = parse_one_ctrip(p, default_year)
            if t["start"]:
                trips.append(t)
        except Exception as e:
            print(f"  ⚠️ 携程 PDF 解析失败 {p}: {e}")

    merged = merge_intervals(trips)

    print(f"\n  合并后区间数: {len(merged)}")
    for t in merged:
        print(f"    → {t['start']} ~ {t['end']}  {t['from_city']}→{t['to_city']}")

    return merged
