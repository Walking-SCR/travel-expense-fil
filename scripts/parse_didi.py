"""
parse_didi.py — 打车行程单解析（Y 坐标分组法 + 通用解析器）

支持：
- 滴滴出行行程单（Y 坐标分组法）
- 阳光出行、呼我出行（百度打车）等通用打车平台
- 高速通行费电子行程单自动匹配

用法:
    from parse_didi import parse_all_rides, classify_didi
    ride_list = parse_all_rides(ride_pdfs, default_year=2025)
    result = classify_didi(ride_list, merged_trips, base_city)
"""
import sys, fitz, re
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import norm_city


# 常见城市关键词
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

# 城市短名（不带"市"后缀）
CITY_SHORT = {kw.replace("市", "") for kw in CITY_KEYWORDS}


# ═══════════════════════════════════════════════════════════════
# 滴滴专用解析器（Y 坐标分组法）
# ═══════════════════════════════════════════════════════════════

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
    t = text.strip()
    return bool(re.search(r'\d{2}-\d{2}\s+\d{2}:\d{2}', t))


def _find_city_nearby(spans, date_y, radius=12):
    """在 date_y ± radius 范围内找最近的城市名 span。返回城市名（如"广州"）或空字符串。"""
    nearby = [s for s in spans if abs(s["y"] - date_y) <= radius]
    for sp in nearby:
        txt = sp["text"].strip()
        for full_kw in CITY_KEYWORDS:
            city = full_kw.replace("市", "")
            if txt == city or txt == full_kw or city[:2] in txt:
                return city
    return ""


def _extract_origin_dest(spans, date_y, radius=30, cache={}):
    """在 date_y ± radius 范围内提取起点和终点地址。"""
    spans_id = id(spans)
    if spans_id not in cache:
        col_idx = {}
        for s in spans:
            t = s["text"].strip()
            if t == "起点" or t == "上车地点" or ("上车" in t and "时间" not in t and "日期" not in t):
                col_idx["origin"] = round(s["x"])
            elif t == "终点" or "目的" in t:
                col_idx["dest"] = round(s["x"])
        cache[spans_id] = col_idx

    col_idx = cache[spans_id]
    origin, dest = "", ""

    if "origin" in col_idx and "dest" in col_idx:
        ox, dx = col_idx["origin"], col_idx["dest"]
        row_spans = sorted(
            [s for s in spans if abs(s["y"] - date_y) <= radius and s["x"] >= min(ox, dx) - 20],
            key=lambda s: s["x"]
        )
        for s in row_spans:
            tx = round(s["x"])
            t = s["text"].strip()
            if not t or re.match(r'^\d', t):
                continue
            if not origin and abs(tx - ox) < 40:
                origin = t
            elif not dest and abs(tx - dx) < 40:
                dest = t
            if origin and dest:
                break

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
    """解析单个滴滴行程单 PDF（Y 坐标分组法）。"""
    spans = _collect_all_spans(pdf_path)

    trips = []
    for sp in spans:
        if not _is_date_span(sp["text"]):
            continue

        m = re.search(r'(\d{2})-(\d{2})\s+\d{2}:\d{2}', sp["text"])
        if not m:
            continue
        month, day = int(m.group(1)), int(m.group(2))
        try:
            trip_date = date(default_year, month, day)
        except ValueError:
            continue

        y = sp["y"]
        city = _find_city_nearby(spans, y, radius=12)
        origin, dest = _extract_origin_dest(spans, y, radius=30)

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
                "time": None,  # 滴滴不提取具体时间
                "source": "滴滴",
            })

    print(f"  [滴滴] {Path(pdf_path).name}: {len(trips)} 条记录")
    for t in trips:
        print(f"    {t['date']} {t['city']} {t['from']}→{t['to']} {t['amount']}元")

    return trips


# ═══════════════════════════════════════════════════════════════
# 通行费电子行程单解析
# ═══════════════════════════════════════════════════════════════

def parse_toll_receipt(pdf_path):
    """解析高速通行费电子行程单，返回 list of toll dicts。"""
    doc = fitz.open(str(pdf_path))
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()

    # 仅处理通行费电子行程单
    if "通行费电子行程单" not in full_text and "通行费" not in full_text:
        return []

    tolls = []

    # 提取金额
    amt_m = re.search(r'发票金额[：:]\s*([\d.]+)元', full_text)
    amt = float(amt_m.group(1)) if amt_m else 0.0

    if amt <= 0:
        return []

    # 通行费格式有两种：
    # A) "入口时间\n2026-04-21 ...\n入口站\n..."  (标签值交替)
    # B) "入口时间\n入口站\n出口时间\n出口站\n交易金额\n2026-04-21 ...\n..."  (所有标签先，所有值后)
    # 统一提取所有日期和金额
    all_dates = re.findall(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', full_text)
    all_stations = re.findall(r'([一-龥]+[-—][一-龥]+(?:站)?)', full_text)

    entry_time = None
    exit_time = None
    if len(all_dates) >= 2:
        try:
            entry_time = datetime.strptime(all_dates[0], "%Y-%m-%d %H:%M:%S")
            exit_time = datetime.strptime(all_dates[1], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    elif len(all_dates) == 1:
        try:
            entry_time = datetime.strptime(all_dates[0], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    entry_station = all_stations[0] if len(all_stations) >= 1 else ""
    exit_station = all_stations[1] if len(all_stations) >= 2 else ""

    toll = {
        "amount": round(amt, 2),
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry_station": entry_station,
        "exit_station": exit_station,
    }

    if entry_time:
        toll["date"] = date(entry_time.year, entry_time.month, entry_time.day)
    elif exit_time:
        toll["date"] = date(exit_time.year, exit_time.month, exit_time.day)

    tolls.append(toll)
    print(f"  [通行费] {Path(pdf_path).name}: {toll['date'] if 'date' in toll else '?'} {amt}元")
    return tolls


# ═══════════════════════════════════════════════════════════════
# 通用打车行程单解析（阳光出行、呼我出行/百度打车等）
# ═══════════════════════════════════════════════════════════════

def parse_generic_ride_hailing(pdf_path, default_year=2025):
    """通用打车行程单解析，支持阳光出行、呼我出行（百度地图）、高德等平台。"""
    doc = fitz.open(str(pdf_path))
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()

    # 跳过通行费电子行程单（由 parse_toll_receipt 处理）
    if "通行费电子行程单" in full_text:
        return []

    # 跳过携程商旅
    if "携程商旅" in full_text or "ctrip" in full_text.lower():
        return []

    trips = []

    # ── 模式一：表格格式（阳光出行、呼我出行等）──
    # 查找表头行确定列位置
    lines = full_text.split('\n')

    # 尝试匹配 "序号" 开头的表格行
    table_rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 匹配序号开头的行（数字开头）
        if re.match(r'^\d+\s', line):
            table_rows.append(line)

    for row_text in table_rows:
        trip = _parse_table_row(row_text, default_year, full_text)
        if trip:
            trips.append(trip)

    # ── 模式二：按行位置解析（每字段一行，优先于键值对）──
    if not trips:
        trips = _parse_line_position_format(full_text, default_year)

    # ── 模式三：键值对格式（从全文提取）──
    if not trips:
        trip = _parse_key_value_format(full_text, default_year)
        if trip:
            trips.append(trip)

    # ── 模式四：从文件名提取金额兜底 ──
    if not trips:
        fname = Path(pdf_path).name
        amt_m = re.search(r'(\d+\.?\d*)元', fname)
        if amt_m:
            amt = float(amt_m.group(1))
            # 尝试从全文提取日期
            d = _extract_date_from_text(full_text, default_year)
            if d and amt > 0:
                trips.append({
                    "date": d,
                    "city": _extract_city_from_text(full_text),
                    "amount": amt,
                    "from": _extract_field_from_text(full_text, ["上车地点", "起点", "出发地"]),
                    "to": _extract_field_from_text(full_text, ["下车地点", "终点", "目的地"]),
                    "time": None,
                    "source": "文件名兜底",
                })

    label = "通用打车"
    # 识别平台名
    for kw in ["阳光出行", "呼我出行", "百度地图", "高德", "花小猪", "T3出行", "曹操出行"]:
        if kw in full_text:
            label = kw
            break

    print(f"  [{label}] {Path(pdf_path).name}: {len(trips)} 条记录")
    for t in trips:
        print(f"    {t['date']} {t['city']} {t['from']}→{t['to']} {t['amount']}元")

    return trips


def _parse_line_position_format(full_text, default_year):
    """当 PDF 每个字段单独一行时，通过表头-数据行位置对应来解析行程。"""
    # 合并日期+时间拆分
    raw_lines = [l.strip() for l in full_text.split('\n') if l.strip()]
    lines = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if re.match(r'^\d{4}-\d{2}-\d{2}$', line) and i + 1 < len(raw_lines):
            next_line = raw_lines[i + 1].lstrip()
            if re.match(r'^\d{2}:\d{2}:\d{2}$', next_line):
                lines.append(f"{line} {next_line}")
                i += 2
                continue
        lines.append(line)
        i += 1

    # 找表头起始
    header_start = None
    for j, line in enumerate(lines):
        if line == '序号':
            header_start = j
            break
    if header_start is None:
        return []

    # 收集表头字段
    header_fields = []
    data_start = None
    for j in range(header_start, len(lines)):
        line = lines[j]
        if re.match(r'^\d+$', line) and j > header_start + 1:
            data_start = j
            break
        header_fields.append(line)

    if data_start is None or len(header_fields) < 3:
        return []

    field_count = len(header_fields)
    data_fields = lines[data_start:data_start + field_count]

    if len(data_fields) < 3:
        return []

    # 提取各字段值
    def _get_field(kw_list):
        for kw in kw_list:
            for j, hf in enumerate(header_fields):
                if hf == kw and j < len(data_fields):
                    return data_fields[j]
        return ""

    date_str = _get_field(['服务时间', '用车时间', '行程时间'])
    city = _get_field(['用车城市', '城市'])
    from_val = _get_field(['上车地点', '起点', '出发地'])
    to_val = _get_field(['下车地点', '终点', '目的地'])
    amt_str = _get_field(['金额(元)', '金额', '可开票金额'])

    # 解析日期
    d = None
    for m in re.finditer(r'(\d{4})[-.](\d{1,2})[-.](\d{1,2})', date_str):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            break
        except ValueError:
            pass
    if not d:
        d = _extract_date_from_text(full_text, default_year)
    if not d:
        return []

    # 解析金额
    amt = 0.0
    amt_m = re.search(r'(\d+\.\d{2})', amt_str.replace('￥', '').replace('¥', ''))
    if amt_m:
        amt = float(amt_m.group(1))

    if amt <= 0:
        # 尝试从数据行中找金额
        for f in data_fields:
            m = re.search(r'(\d+\.\d{2})', f.replace('￥', '').replace('¥', ''))
            if m:
                amt = float(m.group(1))
                if 1 < amt < 500:
                    break

    if amt <= 0:
        return []

    # 过滤无效值
    INVALID = {'可开票金额', '序号', '订单号', '车型', '快车', '经济', '舒适', '呼我出行', '阳光出行',
               '用车时间', '服务时间', '服务方', '用车城市', '用车里程', '金额', '可开票', '订单',
               '公里', '起点', '终点', '上车地点', '下车地点', '出发地', '目的地', '滴滴', 'T3出行'}

    if from_val in INVALID:
        from_val = ""
    if to_val in INVALID:
        to_val = ""

    # 提取时间
    trip_time = None
    time_m = re.search(r'(\d{2}:\d{2}:\d{2})', date_str)
    if time_m:
        try:
            trip_time = datetime.strptime(time_m.group(1), "%H:%M:%S").time()
        except ValueError:
            pass

    return [{
        "date": d,
        "city": city if city not in INVALID else _extract_city_from_text(full_text),
        "amount": round(amt, 2),
        "from": from_val,
        "to": to_val,
        "time": trip_time,
        "source": "行位置解析",
    }]


def _parse_table_row(row_text, default_year, full_text):
    """解析表格行格式的行程数据。"""
    trip = {"date": None, "city": "未知", "amount": 0.0, "from": "", "to": "", "time": None, "source": "通用"}

    # ── 金额：last field 或 "XX.XX" 格式 ──
    amounts = re.findall(r'(\d+\.\d{2})', row_text)
    if amounts:
        valid = [float(a) for a in amounts if 1 < float(a) < 500]
        if valid:
            trip["amount"] = max(valid)

    if trip["amount"] <= 0:
        return None

    # ── 日期：从行内提取，或从全文上下文提取 ──
    # 支持 "2026-04-21 07:38:38"、"2026.04.21"、"04-21"
    date_m = re.search(r'(\d{4})[-.](\d{1,2})[-.](\d{1,2})', row_text)
    if date_m:
        try:
            trip["date"] = date(int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3)))
        except ValueError:
            pass

    if not trip["date"]:
        # 尝试从上下文提取（行所属的全文区域）
        trip["date"] = _extract_date_from_text(full_text, default_year)

    if not trip["date"]:
        return None  # 必须有日期

    # ── 城市 ──
    trip["city"] = _extract_city_from_text(row_text) or _extract_city_from_text(full_text)

    # ── 起点/终点：从全文定位 ——
    # 阳光出行表头：上车地点 / 下车地点
    # 百度打车表头：起点 / 终点
    trip["from"] = _extract_field_from_row(row_text, full_text, ["上车地点", "起点", "出发地"])
    trip["to"] = _extract_field_from_row(row_text, full_text, ["下车地点", "终点", "目的地"])

    # ── 时间 ──
    time_m = re.search(r'(\d{2}:\d{2}:\d{2})', row_text)
    if time_m:
        try:
            t = datetime.strptime(time_m.group(1), "%H:%M:%S").time()
            trip["time"] = t
        except ValueError:
            pass

    return trip


def _parse_key_value_format(full_text, default_year):
    """解析键值对格式的行程单（如 Uber、Lyft 等）。"""
    d = _extract_date_from_text(full_text, default_year)
    if not d:
        return None

    amts = re.findall(r'[¥￥]\s*(\d+\.\d{2})', full_text)
    if not amts:
        amts = re.findall(r'合计[：:]\s*(\d+\.\d{2})', full_text)
    if not amts:
        return None

    amt = max(float(a) for a in amts if 1 < float(a) < 500)
    if amt <= 0:
        return None

    return {
        "date": d,
        "city": _extract_city_from_text(full_text),
        "amount": round(amt, 2),
        "from": _extract_field_from_row("", full_text, ["上车地点", "起点", "出发地"]),
        "to": _extract_field_from_row("", full_text, ["下车地点", "终点", "目的地"]),
        "time": None,
        "source": "通用(键值对)",
    }


def _extract_date_from_text(text, default_year):
    """从文本中提取日期。支持多种格式。优先取「行程日期/服务时间」，避免「申请日期」。"""
    # 优先级1：明确标注的行程/服务日期
    for kw in ['行程日期', '行程时间', '服务时间', '用车时间']:
        m = re.search(rf'{kw}[：:]\s*(\d{{4}})[-.](\d{{1,2}})[-.](\d{{1,2}})', text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

    # 优先级2：正文中第一个出现的完整日期
    # 但要跳过 "申请日期"、"开票时间" 等
    skip_prefixes = ['申请日期', '开票时间', '制作时间', '发票']
    for m in re.finditer(r'(\d{4})[-.](\d{1,2})[-.](\d{1,2})', text):
        # 检查前面是否有跳过词
        before = text[max(0, m.start()-20):m.start()]
        if any(skip in before for skip in skip_prefixes):
            continue
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # 优先级3：任何完整的日期格式
    for m in re.finditer(r'(\d{4})[-.](\d{1,2})[-.](\d{1,2})', text):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # 优先级4："MM-DD" + 已知年份
    m = re.search(r'(\d{1,2})[-.](\d{1,2})', text)
    if m:
        mo, dy = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            try:
                return date(default_year, mo, dy)
            except ValueError:
                pass
    return None


def _extract_city_from_text(text):
    """从文本中提取城市名。"""
    for city in sorted(CITY_SHORT, key=len, reverse=True):
        if city in text:
            return city
    for kw in CITY_KEYWORDS:
        if kw in text:
            return kw.replace("市", "")
    return "未知"


def _extract_field_from_text(text, keywords):
    """从文本中提取指定关键字段后的值（支持多行、多词地址）。

    优先匹配数据区的关键字（跳过表头行）。
    """
    # 先找表头行位置（含"序号"的行），优先匹配表头之后的数据
    header_end = 0
    header_m = re.search(r'(?:序号|订单号)\s', text)
    if header_m:
        # 找到表头后的第一个数据行起始位置
        header_end = header_m.end()

    for kw in keywords:
        # 尝试多行匹配 — 从表头后面开始搜
        search_text = text[header_end:] if header_end > 0 else text
        m = re.search(rf'{kw}\s*\n\s*([^\n]+)', search_text)
        if not m:
            # 回退到全文搜索
            m = re.search(rf'{kw}\s*\n\s*([^\n]+)', text)

        if m:
            val = m.group(1).strip()
            # 过滤掉明显的非地址值（金额、表头关键字、纯数字）
            if val in ('可开票金额', '序号', '订单号', '车型', ''):
                continue
            if re.match(r'^[\d.¥￥\s]+$', val):
                continue
            if len(val) >= 2:
                return val

        # 退而求其次：单行匹配
        m2 = re.search(rf'{kw}\s*\n?\s*(\S+)', search_text if header_end > 0 else text)
        if not m2:
            m2 = re.search(rf'{kw}\s*\n?\s*(\S+)', text)
        if m2:
            val = m2.group(1).strip()
            if val in ('可开票金额', '序号', '订单号', '车型', ''):
                continue
            if not re.match(r'^[\d.¥￥]+$', val) and len(val) >= 2:
                return val
    return ""


def _extract_field_from_row(row_text, full_text, keywords):
    """从表格行或全文中提取字段值。先查行内上下文，再回退到全文提取。"""
    # 已知的无效值（表头关键字、非地址元数据）
    INVALID = {'可开票金额', '序号', '订单号', '车型', '快车', '经济', '舒适',
               '用车时间', '服务时间', '服务方', '用车城市', '用车里程', '金额',
               '可开票', '订单', '公里', '起点', '终点', '上车地点', '下车地点',
               '出发地', '目的地', '呼我出行', '阳光出行', '滴滴', 'T3出行'}

    val = _extract_field_from_text(row_text, keywords)
    if val and val not in INVALID:
        return val
    val = _extract_field_from_text(full_text, keywords)
    if val and val not in INVALID:
        return val
    # 最后手段：按行位置匹配（每个字段一行时）
    val = _extract_by_line_position(full_text, keywords)
    if val and val not in INVALID:
        return val
    return ""


def _extract_by_line_position(text, keywords):
    """当 PDF 每个字段单独一行时，通过表头列位置提取对应数据值。

    例如：序号\\n...\\n起点\\n终点\\n...\\n1\\n...\\n新塘站\\n龙光峰景华庭\\n...
    表头中"起点"在第 N 个字段，数据行中第 N 个字段就是起点值。
    """
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]

    # 预处理：合并日期+时间拆分的相邻行（如 "2026-04-21" + "15:21:52" → "2026-04-21 15:21:52"）
    lines = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if re.match(r'^\d{4}-\d{2}-\d{2}$', line) and i + 1 < len(raw_lines):
            next_line = raw_lines[i + 1]
            if re.match(r'^\d{2}:\d{2}:\d{2}$', next_line):
                lines.append(f"{line} {next_line}")
                i += 2
                continue
        lines.append(line)
        i += 1

    # 1. 找表头行（含"序号"的行开始）
    header_start = None
    for i, line in enumerate(lines):
        if line == '序号':
            header_start = i
            break
    if header_start is None:
        return ""

    # 从 header_start 开始收集表头字段，直到遇到第一个数字（数据行开始）
    header_fields = []
    data_start = None
    for i in range(header_start, len(lines)):
        line = lines[i]
        if re.match(r'^\d+$', line) and i > header_start + 1:
            data_start = i
            break
        header_fields.append(line)

    if data_start is None or not header_fields:
        return ""

    # 确定每个数据行有多少字段（与表头一致）
    field_count = len(header_fields)
    # 数据行：从 data_start 开始的 field_count 个字段
    data_fields = lines[data_start:data_start + field_count]

    # 如果数据字段数 < 表头数，用实际数据字段数
    actual_count = min(field_count, len(data_fields))
    if actual_count == 0:
        return ""

    # 查找关键字在表头中的位置
    for kw in keywords:
        for j, hf in enumerate(header_fields):
            if hf == kw and j < actual_count:
                val = data_fields[j]
                # 验证是地址不是元数据
                if val and not re.match(r'^[\d.¥￥\s]+$', val) and \
                   val not in ('可开票金额', '序号', '订单号', '车型', '快车', '经济', '舒适'):
                    return val
    return ""


# ═══════════════════════════════════════════════════════════════
# 通行费匹配
# ═══════════════════════════════════════════════════════════════

def _match_tolls_to_rides(rides, tolls):
    """将通行费按时间匹配到最近的打车行程。

    匹配策略：优先按时间窗口（±2h），若无精确时间则按同日匹配。
    返回 (matched_rides, unmatched_tolls)。
    """
    if not tolls:
        return rides, []

    matched_toll_idxs = set()

    for i, toll in enumerate(tolls):
        if "date" not in toll:
            continue
        toll_dt = toll.get("entry_time")
        toll_has_exact_time = toll_dt is not None
        if not toll_dt:
            toll_dt = datetime.combine(toll["date"], datetime.min.time())

        best_ride = None
        best_diff = timedelta(hours=25)  # 放宽到同日

        for ride in rides:
            if ride["date"] != toll["date"]:
                continue
            ride_dt = ride.get("time")
            ride_has_exact_time = ride_dt is not None
            if not ride_dt:
                ride_dt = datetime.combine(ride["date"], datetime.min.time())
            else:
                ride_dt = datetime.combine(ride["date"], ride_dt)

            diff = abs((toll_dt - ride_dt).total_seconds())

            # 如果双方都有精确时间，使用 2h 窗口
            if toll_has_exact_time and ride_has_exact_time:
                if diff > 7200:  # 2 hours
                    continue
            # 否则仅要求同日（diff < 24h）
            elif diff > 86400:
                continue

            if diff < best_diff.total_seconds():
                best_diff = timedelta(seconds=diff)
                best_ride = ride

        if best_ride is not None:
            best_ride["amount"] += toll["amount"]
            best_ride["amount"] = round(best_ride["amount"], 2)
            matched_toll_idxs.add(i)
            print(f"    🔗 通行费 {toll['amount']}元 匹配 → {best_ride['date']} {best_ride.get('from','?')}→{best_ride.get('to','?')}")

    unmatched = [t for i, t in enumerate(tolls) if i not in matched_toll_idxs]
    if unmatched:
        print(f"  ⚠️ {len(unmatched)} 笔通行费未匹配到打车行程")

    return rides, unmatched


# ═══════════════════════════════════════════════════════════════
# 对外 API
# ═══════════════════════════════════════════════════════════════

def parse_all_rides(pdf_paths, default_year=2025):
    """解析所有打车 PDF（滴滴 + 通用），合并通行费后返回。

    对每个 PDF：
    1. 先尝试滴滴专用解析器
    2. 返回 0 条则降级到通用解析器
    3. 收集通行费，最后按时间匹配
    """
    all_rides = []
    all_tolls = []

    for p in pdf_paths:
        p_str = str(p)
        # 先尝试通行费解析
        tolls = parse_toll_receipt(p_str)
        if tolls:
            all_tolls.extend(tolls)
            continue

        # 尝试滴滴解析
        didi_ok = False
        try:
            didi_result = parse_one_didi(p_str, default_year)
            if didi_result:
                # 检查是否所有记录都缺少 from/to（可能是非滴滴格式被误识别）
                has_address = any(r.get("from") and r.get("to") for r in didi_result)
                if has_address:
                    all_rides.extend(didi_result)
                    didi_ok = True
                    continue
                # from/to 缺失 → 降级到通用解析器获取完整数据
        except Exception as e:
            pass  # 降级到通用解析

        # 通用解析
        if not didi_ok:
            try:
                generic_result = parse_generic_ride_hailing(p_str, default_year)
                if generic_result:
                    # 如果滴滴已有部分数据，用通用结果补充（优先通用解析的from/to）
                    if didi_result:
                        for gr in generic_result:
                            # 按日期+金额匹配补充
                            for dr in didi_result:
                                if dr["date"] == gr["date"] and abs(dr["amount"] - gr["amount"]) < 1:
                                    if not dr.get("from"):
                                        dr["from"] = gr.get("from", "")
                                    if not dr.get("to"):
                                        dr["to"] = gr.get("to", "")
                                    if not dr.get("city") or dr["city"] == "未知":
                                        dr["city"] = gr.get("city", dr["city"])
                                    gr["_merged"] = True
                            if not gr.get("_merged"):
                                all_rides.append(gr)
                        all_rides.extend([r for r in didi_result if r.get("from") or r.get("to")])
                        # 如果滴滴结果都没地址，只用通用结果
                        if not any(r.get("from") or r.get("to") for r in didi_result):
                            pass  # didi_result discarded, generic already added
                        elif not generic_result:
                            all_rides.extend(didi_result)
                    else:
                        all_rides.extend(generic_result)
            except Exception as e:
                print(f"  ⚠️ 通用打车 PDF 解析失败 {p}: {e}")
                if didi_result:
                    all_rides.extend(didi_result)

    # 按日期排序
    all_rides.sort(key=lambda x: x["date"])

    # 通行费匹配
    all_rides, unmatched_tolls = _match_tolls_to_rides(all_rides, all_tolls)

    print(f"\n  打车合计 {len(all_rides)} 条记录")
    if unmatched_tolls:
        total_toll = sum(t["amount"] for t in unmatched_tolls)
        print(f"  ⚠️ 未匹配通行费 {len(unmatched_tolls)} 笔，合计 {total_toll}元")

    return all_rides


# 兼容旧 API
parse_all_didi = parse_all_rides


def classify_didi(didi_list, merged_trips, base_city):
    """
    将打车记录分类到「出差地」或「Base地」。

    Base地使用列表结构，支持同日多笔行程。

    返回:
        {
            "trip": {date: {"amount": float, "from": str, "to": str}, ...},
            "base": {date: [{"amount": float, "from": str, "to": str}, ...], ...},
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

    # trip: 按日期合并金额（差旅费 I 列单日单金额）
    trip_map = defaultdict(lambda: {"amount": 0.0, "from": "", "to": ""})
    # base: 按日期保留列表（支持同日多行）
    base_map = defaultdict(list)
    unknown = []

    for d in didi_list:
        cn = norm_city(d["city"])
        entry = {
            "amount": d["amount"],
            "from": d.get("from", ""),
            "to": d.get("to", ""),
        }

        if cn == norm_base:
            base_map[d["date"]].append(entry)
        elif cn in dest_cities:
            trip_map[d["date"]]["amount"] += d["amount"]
            if not trip_map[d["date"]]["from"]:
                trip_map[d["date"]]["from"] = d.get("from", "")
                trip_map[d["date"]]["to"] = d.get("to", "")
        else:
            unknown.append(d)

    return {
        "trip": {k: dict(v) for k, v in trip_map.items()},
        "base": {k: list(v) for k, v in base_map.items()},
        "unknown": unknown,
    }
