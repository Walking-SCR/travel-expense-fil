"""
parse_ticket.py — 火车票/大巴票解析

用法:
    from parse_ticket import parse_train_ticket, parse_bus_ticket
    t = parse_train_ticket(pdf_path)   # -> {"date": date, "amount": float}
    b = parse_bus_ticket(pdf_path)     # -> {"date": date, "amount": float}
"""
import sys, fitz, re
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _extract_pdf_text(pdf_path):
    doc = fitz.open(str(pdf_path))
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def resolve_city_from_station(station_name):
    if not station_name:
        return ""
    station_name = station_name.strip()
    
    # 1. 包含已知地级市名
    for c in ["广州", "深圳", "珠海", "北京", "上海", "香港", "东莞", "佛山", "杭州", "成都", "武汉", "南京", "西安", "重庆", "天津", "长沙"]:
        if c in station_name:
            return c
            
    # 2. 包含广州区名或地标
    gz_kws = ["天河", "越秀", "荔湾", "海珠", "白云", "黄埔", "番禺", "花都", "增城", "从化", "南沙", "三溪", "广州"]
    for kw in gz_kws:
        if kw in station_name:
            return "广州"
            
    # 3. 包含深圳区名或地标
    sz_kws = ["福田", "罗湖", "南山", "盐田", "宝安", "龙岗", "龙华", "坪山", "光明", "大鹏", "深圳"]
    for kw in sz_kws:
        if kw in station_name:
            return "深圳"
            
    return station_name


def parse_train_ticket(pdf_path):
    """
    解析火车票（铁路电子客票，12306格式）。

    12306 票据典型字段：
      出发时间：2025年12月06日 08:30
      到达时间：2025年12月06日 12:45
      票价：¥ 325.00
      出发地：北京
      目的地：上海
    """
    text = _extract_pdf_text(pdf_path)

    # 日期：优先行程日期（带发车时间），其次出发时间，跳过开票日期
    # 1. "2026年03月25日\n22:00开" — 行程日期 + 发车时间
    dm = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*\n?\s*(\d{2}:\d{2})', text)
    if not dm:
        # 2. "出发时间：2025年12月06日"
        dm = re.search(r'出发时间[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if not dm:
        dm = re.search(r'开乘日期[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if not dm:
        # 3. 所有 YYYY年MM月DD日，但跳过"开票日期"前缀的
        for m in re.finditer(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text):
            before = text[max(0, m.start()-12):m.start()]
            if '开票' in before:
                continue
            dm = m
            break
    if not dm:
        dm = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', text)

    if dm:
        ticket_date = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    else:
        ticket_date = None
        print(f"  ⚠️ 火车票日期解析失败: {Path(pdf_path).name}")

    # 金额：优先 ¥/￥ 符号，其次「票价」字段
    am = re.search(r'[¥￥]\s*(\d+\.?\d*)', text)
    if not am:
        am = re.search(r'票价[：:]?\s*[\s\S]*?[¥￥]\s*(\d+\.?\d*)', text)
    if not am:
        am = re.search(r'(\d{2,}\.\d{2})', text)  # 两位及以上整数 + 小数

    if am:
        amount = float(am.group(1))
    else:
        amount = 0.0
        print(f"  ⚠️ 火车票金额解析失败: {Path(pdf_path).name}")

    # 提取出发地与目的地，解析出城市
    from_m = re.search(r'出发地[：:]\s*([^\n]+)', text)
    if not from_m:
        from_m = re.search(r'始发站[：:]\s*([^\n]+)', text)
    if not from_m:
        from_m = re.search(r'乘车站[：:]\s*([^\n]+)', text)

    to_m = re.search(r'目的地[：:]\s*([^\n]+)', text)
    if not to_m:
        to_m = re.search(r'到达站[：:]\s*([^\n]+)', text)
    if not to_m:
        to_m = re.search(r'到站[：:]\s*([^\n]+)', text)

    from_station = from_m.group(1).strip() if from_m else ""
    to_station = to_m.group(1).strip() if to_m else ""

    from_city = resolve_city_from_station(from_station)
    to_city = resolve_city_from_station(to_station)

    return {
        "date": ticket_date,
        "amount": amount,
        "from_city": from_city,
        "to_city": to_city
    }


def parse_bus_ticket(pdf_path):
    """
    解析大巴票/汽车票。

    大巴票典型字段：
      日期：2025年12月06日
      金额：¥45.00

    也支持 YYYY-MM-DD HH:MM 格式（常见大巴 PDF）。
    """
    text = _extract_pdf_text(pdf_path)

    # 日期
    dm = re.search(r'日期[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if not dm:
        dm = re.search(r'开票日期[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if not dm:
        dm = re.search(r'乘车日期[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if not dm:
        dm = re.search(r'(\d{4})-(\d{2})-(\d{2})\s+\d{2}:\d{2}', text)
    if not dm:
        dm = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', text)

    if dm:
        ticket_date = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    else:
        ticket_date = None
        print(f"  ⚠️ 大巴票日期解析失败: {Path(pdf_path).name}")

    # 金额
    am = re.search(r'金额[：:]\s*[¥￥]?\s*(\d+\.?\d*)', text)
    if not am:
        am = re.search(r'票价[：:]\s*[¥￥]?\s*(\d+\.?\d*)', text)
    if not am:
        am = re.search(r'¥\s*(\d+\.?\d*)', text)
    if not am:
        am = re.search(r'(\d+\.\d{2})', text)  # 兜底：任何小数

    if am:
        amount = float(am.group(1))
    else:
        amount = 0.0
        print(f"  ⚠️ 大巴票金额解析失败: {Path(pdf_path).name}")

    # 提取出发地与目的地，并解析出城市
    from_m = re.search(r'上车站点[：:]?\s*([^\n]+)', text)
    if not from_m:
        from_m = re.search(r'出发站[：:]?\s*([^\n]+)', text)
    if not from_m:
        from_m = re.search(r'上车地点[：:]?\s*([^\n]+)', text)

    to_m = re.search(r'下车站点[：:]?\s*([^\n]+)', text)
    if not to_m:
        to_m = re.search(r'到达站[：:]?\s*([^\n]+)', text)
    if not to_m:
        to_m = re.search(r'下车地点[：:]?\s*([^\n]+)', text)

    from_station = from_m.group(1).strip() if from_m else ""
    to_station = to_m.group(1).strip() if to_m else ""

    from_city = resolve_city_from_station(from_station)
    to_city = resolve_city_from_station(to_station)

    return {
        "date": ticket_date,
        "amount": amount,
        "from_city": from_city,
        "to_city": to_city
    }
