"""
parse_didi.py — 滴滴行程单解析（Y 坐标分组法）

v2/v3 核心修复：滴滴 PDF 中城市名（如"广州市"）可能被 fitz 拆成
"广"+"州"两行，用 Y 坐标关联法解决。

用法:
    from parse_didi import parse_all_didi, classify_didi
    didi_list = parse_all_didi(didi_pdfs, default_year=2025)
    result = classify_didi(didi_list, merged_trips, base_city)
"""
import sys, fitz, re
from datetime import date
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import norm_city


# 滴滴行程单中常见的城市关键词（首字/尾字，用于跨行检测）
CITY_KEYWORDS = [
    "广州市", "深圳市", "珠海市", "东莞市", "佛山市",
    "香港市", "北京市", "上海市", "杭州市", "成都市",
    "武汉市", "南京市", "西安市", "重庆市", "天津市",
    "长沙市", "郑州市", "青岛市", "厦门市", "沈阳市",
    "大连市", "苏州市", "济南市", "福州市", "昆明市",
    "哈尔滨市", "合肥市", "南昌市", "石家庄市", "太原市",
    "贵阳市", "南宁市", "兰州市", "海口市", "银川市",
    "西宁市", "拉萨市", "乌鲁木齐市", "呼和浩特市", "澳门市",
]


def _collect_all_spans(pdf_path):
    """提取 PDF 所有文本块，返回 list of {text, y, x}，按 y 升序。"""
    doc = fitz.open(str(pdf_path))
    spans = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = span["text"].strip()
                    if txt:
                        spans.append({
                            "text": txt,
                            "y": round(span["bbox"][1]),
                            "x": span["bbox"][0],
                        })
    doc.close()
    spans.sort(key=lambda s: s["y"])
    return spans


def _is_date_span(text):
    """判断 span 是否为日期时间行（接受形如 '12-24 16:28 周' 格式）。"""
    # 去掉首尾空白
    t = text.strip()
    # 支持 "12-24 16:28" 或 "12-24 16:28 周三" 等尾随内容
    return bool(re.search(r'\d{2}-\d{2}\s+\d{2}:\d{2}', t))


def _find_city_nearby(spans, date_y, radius=12):
    """在 date_y ± radius 范围内找最近的城市名 span。返回城市名（如"广州"）或空字符串。"""
    nearby = [s for s in spans if abs(s["y"] - date_y) <= radius]
    for sp in nearby:
        txt = sp["text"].strip()
        # 去掉"市"后缀后匹配
        for full_kw in CITY_KEYWORDS:
            city = full_kw.replace("市", "")
            if txt == city or txt == full_kw or city[:2] in txt:
                return city
    return ""


def _extract_origin_dest(spans, date_y, radius=30, cache={}):
    """在 date_y ± radius 范围内提取起点和终点地址。

    优化：先通过全局扫描 spans 定位 "起点" 和 "终点" 所在的 x 轴坐标列中心点，
    然后在 date_y 附近精准匹配。
    """
    spans_id = id(spans)
    if spans_id not in cache:
        col_idx = {}
        for s in spans:
            t = s["text"].strip()
            # 避免将"上车时间"误判为"起点"列
            if t == "起点" or t == "上车地点" or ("上车" in t and "时间" not in t and "日期" not in t):
                col_idx["origin"] = round(s["x"])
            elif t == "终点" or "目的" in t:
                col_idx["dest"] = round(s["x"])
        cache[spans_id] = col_idx

    col_idx = cache[spans_id]
    origin, dest = "", ""

    if "origin" in col_idx and "dest" in col_idx:
        ox, dx = col_idx["origin"], col_idx["dest"]
        # 找同一行（date_y 附近）最近行的起点/终点值（扩大下限支持偏移）
        row_spans = sorted(
            [s for s in spans if abs(s["y"] - date_y) <= radius and s["x"] >= min(ox, dx) - 20],
            key=lambda s: s["x"]
        )
        for s in row_spans:
            tx = round(s["x"])
            t = s["text"].strip()
            if not t or re.match(r'^\d', t):  # 跳过纯数字（序号、里程、金额等）
                continue
            if not origin and abs(tx - ox) < 40:
                origin = t
            elif not dest and abs(tx - dx) < 40:
                dest = t
            if origin and dest:
                break

    # 如果全局扫描缓存定位失败，退回到局部扫描的兜底逻辑以确保最大兼容性
    if not origin or not dest:
        nearby = [s for s in spans if abs(s["y"] - date_y) <= radius]
        nearby.sort(key=lambda s: s["x"])
        header_y = None
        header_spans = [s for s in nearby if any(k in s["text"] for k in ["起点", "终点", "上车", "目的"])]
        if header_spans:
            header_y = header_spans[0]["y"]
        if header_y is not None:
            all_near = sorted(
                [s for s in spans if abs(s["y"] - header_y) <= radius],
                key=lambda s: s["x"]
            )
            local_cols = {}
            for s in all_near:
                t = s["text"].strip()
                if t == "起点" or "上车" in t:
                    local_cols["origin"] = round(s["x"])
                elif t == "终点" or "目的" in t:
                    local_cols["dest"] = round(s["x"])
            if "origin" in local_cols and "dest" in local_cols:
                lox, ldx = local_cols["origin"], local_cols["dest"]
                row_spans = sorted(
                    [s for s in spans if abs(s["y"] - date_y) <= radius and s["x"] >= min(lox, ldx)],
                    key=lambda s: s["x"]
                )
                for s in row_spans:
                    tx = round(s["x"])
                    t = s["text"].strip()
                    if not t or re.match(r'^\d', t):
                        continue
                    if not origin and abs(tx - lox) < 30:
                        origin = t
                    elif not dest and abs(tx - ldx) < 30:
                        dest = t
                    if origin and dest:
                        break

    return origin.strip(), dest.strip()


def parse_one_didi(pdf_path, default_year=2025):
    """
    解析单个滴滴行程单 PDF。

    算法：
    1. 扫描所有日期时间行（_is_date_span）
    2. 在日期行 y±12pt 范围内找城市名 span（_find_city_nearby）
    3. 在日期行 y±30pt 范围内提取起点/终点地址（_extract_origin_dest）
    4. 在日期行 y±20pt 范围内找金额
    """
    spans = _collect_all_spans(pdf_path)

    trips = []
    for sp in spans:
        if not _is_date_span(sp["text"]):
            continue

        # 提取月日
        m = re.search(r'(\d{2})-(\d{2})\s+\d{2}:\d{2}', sp["text"])
        if not m:
            continue
        month, day = int(m.group(1)), int(m.group(2))
        try:
            trip_date = date(default_year, month, day)
        except ValueError:
            continue

        y = sp["y"]

        # ── 城市匹配（直接扫描近邻 span）──
        city = _find_city_nearby(spans, y, radius=12)

        # ── 起点/终点地址（v3 新增）──
        origin, dest = _extract_origin_dest(spans, y, radius=30)

        # ── 金额匹配（y±20pt 找 XX.XX）──
        nearby = [s for s in spans if abs(s["y"] - y) <= 20]
        amounts = [float(s["text"]) for s in nearby
                   if re.match(r'^\d+\.\d{2}$', s["text"])
                   and 10 < float(s["text"]) < 500]
        amt = max(amounts) if amounts else 0.0

        if amt > 0:
            trips.append({
                "date": trip_date,
                "city": city or "未知",
                "amount": amt,
                "from": origin,
                "to": dest,
            })

    print(f"  [滴滴] {Path(pdf_path).name}: {len(trips)} 条记录")
    for t in trips:
        print(f"    {t['date']} {t['city']} {t['from']}→{t['to']} {t['amount']}元")

    return trips


def parse_all_didi(pdf_paths, default_year=2025):
    """解析所有滴滴 PDF，合并返回。"""
    all_trips = []
    for p in pdf_paths:
        try:
            all_trips.extend(parse_one_didi(p, default_year))
        except Exception as e:
            print(f"  ⚠️ 滴滴 PDF 解析失败 {p}: {e}")

    # 按日期排序
    all_trips.sort(key=lambda x: x["date"])

    print(f"\n  滴滴合计 {len(all_trips)} 条记录")
    return all_trips


def classify_didi(didi_list, merged_trips, base_city):
    """
    将滴滴记录分类到「出差地」或「Base地」。

    返回:
        {
            "trip": {date: {"amount": float, "from": str, "to": str}, ...},
            "base": {date: {"amount": float, "from": str, "to": str}, ...},
            "unknown": [{"date", "city", "amount", "from", "to"}, ...],
        }
    """
    norm_base = norm_city(base_city)

    # 所有出差目的城市
    dest_cities = set()
    for t in merged_trips:
        for c in t["to_city"].split("；"):
            dest_cities.add(norm_city(c))
        if norm_city(t["from_city"]) != norm_base:
            dest_cities.add(norm_city(t["from_city"]))

    trip_map = defaultdict(lambda: {"amount": 0.0, "from": "", "to": ""})
    base_map = defaultdict(lambda: {"amount": 0.0, "from": "", "to": ""})
    unknown = []

    for d in didi_list:
        cn = norm_city(d["city"])
        entry = {
            "amount": d["amount"],
            "from": d.get("from", ""),
            "to": d.get("to", ""),
        }

        if cn == norm_base:
            base_map[d["date"]]["amount"] += d["amount"]
            if not base_map[d["date"]]["from"]:
                base_map[d["date"]]["from"] = d.get("from", "")
                base_map[d["date"]]["to"] = d.get("to", "")
        elif cn in dest_cities:
            trip_map[d["date"]]["amount"] += d["amount"]
            if not trip_map[d["date"]]["from"]:
                trip_map[d["date"]]["from"] = d.get("from", "")
                trip_map[d["date"]]["to"] = d.get("to", "")
        else:
            unknown.append(d)

    return {
        "trip": {k: dict(v) for k, v in trip_map.items()},
        "base": {k: dict(v) for k, v in base_map.items()},
        "unknown": unknown,
    }
