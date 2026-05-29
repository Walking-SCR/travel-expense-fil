"""
fill_trip_xlsx.py — 填写差旅费 Excel（xlsx_edit 重写版）

直接用 xlsx_edit 操作 XML，不走 openpyxl save，
100% 保留模板原始结构（namespace、phoneticPr、calcChain.xml 等）。
"""
import sys
from datetime import datetime as dt, timedelta, date as date_cls
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from xlsx_edit import XlsxEditor
from utils import get_template


def fill_trip_xlsx(out_path, days_data, train_fares, didi_trip, pi, merged_trips,
                   project_info=None):
    """填写「差旅费」Excel。"""
    template_path = get_template("差旅费-template.xlsx")
    ed = XlsxEditor(template_path, out_path)
    ed.load()

    # 项目信息：优先 project_info（每次出差独立），回退到 pi（兼容旧模式）
    pj = project_info or pi

    TRIP_START = 10
    trip_days = len(days_data)
    total_row = TRIP_START + trip_days  # will be actual position after renumber

    # ══ 一、表头填写 ══
    ed.set_cell_text(2, 'C2', pi.get('name', ''))
    ed.set_cell_text(2, 'J2', pi.get('emp_id', ''))
    ed.set_cell_text(2, 'J3', pi.get('manager', ''))
    ed.set_cell_text(2, 'C4', pj.get('project_code') or '无')
    ed.set_cell_text(2, 'J4', pj.get('project_status') or '售前')
    ed.set_cell_text(2, 'C5', pj.get('project_name') or '无')
    pm_val = pj.get('project_manager')
    ed.set_cell_text(2, 'J5', pm_val if pm_val else '无')

    # ══ 二、清数据行（10-42：数据+合计+空行）══
    ed.clear_rows(2, TRIP_START, 42)

    # ══ 三、构建出差事由映射 ══
    trip_reason_map = {}
    for m in (merged_trips or []):
        start = m['start']
        for day_offset in range((m['end'] - m['start']).days + 1):
            d_val = start + timedelta(days=day_offset)
            trip_reason_map[date_cls(d_val.year, d_val.month, d_val.day)] = m.get('reason', '出差')

    subsidy_note = (
        "选择补贴标准二"
        if (merged_trips and merged_trips[0].get('standard', 2) == 2)
        else "选择补贴标准一"
    )

    # ══ 四、填数据行 ══
    for i, day in enumerate(sorted(days_data.keys())):
        row = TRIP_START + i
        d = days_data[day]

        ed.set_cell_date(2, f'A{row}', dt(day.year, day.month, day.day))
        from_city = d.get('from_city', '')
        ed.set_cell_text(2, f'B{row}', from_city)
        ed.set_cell_text(2, f'C{row}', from_city)
        ed.set_cell_text(2, f'D{row}', d.get('to_city', ''))
        ed.set_cell_text(2, f'E{row}', trip_reason_map.get(day, '出差'))
        ed.set_cell_number(2, f'F{row}', d.get('plane', 0))
        ed.set_cell_number(2, f'G{row}', round(train_fares.get(day, 0), 2))
        ed.set_cell_number(2, f'H{row}', d.get('bus', 0))
        didi_entry = didi_trip.get(day)
        didi_val = round(didi_entry['amount'], 2) if didi_entry and didi_entry.get('amount') else 0
        ed.set_cell_number(2, f'I{row}', didi_val)
        ed.set_cell_number(2, f'J{row}', round(d.get('hotel', 0), 2))
        ed.set_cell_number(2, f'K{row}', round(d.get('subsidy', 0), 2))
        ed.set_cell_formula(2, f'L{row}', f'=SUM(F{row}:K{row})')
        ed.set_cell_text(2, f'M{row}', subsidy_note)

    # ══ 五、自动换行 + 自适应行高（数据行整行）══
    for i in range(trip_days):
        row = TRIP_START + i
        for col in ('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M'):
            ed.set_cell_wrap(2, f'{col}{row}')
        ed.set_row_auto_height(2, row)

    # ══ 六、合计行（先写在模板 Row 41，delete_rows 会重编号到 total_row）══
    t = TRIP_START + trip_days - 1  # last data row
    # P63+P64修复：A列写"报销合计"，H列大巴SUM
    ed.set_cell_text(2, 'A41', '报销合计')
    ed.set_cell_formula(2, 'F41', f'=SUM(F{TRIP_START}:F{t})')
    ed.set_cell_formula(2, 'G41', f'=SUM(G{TRIP_START}:G{t})')
    ed.set_cell_formula(2, 'H41', f'=SUM(H{TRIP_START}:H{t})')
    ed.set_cell_formula(2, 'I41', f'=SUM(I{TRIP_START}:I{t})')
    ed.set_cell_formula(2, 'J41', f'=SUM(J{TRIP_START}:J{t})')
    ed.set_cell_formula(2, 'K41', f'=SUM(K{TRIP_START}:K{t})')
    ed.set_cell_formula(2, 'L41', f'=SUM(L{TRIP_START}:L{t})')

    # ══ 七、删除多余行（重编号合计行 41 → total_row）══
    if trip_days < 31:
        # 删除数据行末尾与合计行之间的空隙行（10+N ~ 40）
        ed.delete_rows(2, TRIP_START + trip_days, 41 - (TRIP_START + trip_days))

    ed.strip_calc_chain()
    ed.flush_all()
    print(f"✅ 差旅费已生成: {out_path}")
    print(f"   差旅天数={trip_days}，数据行={TRIP_START}~{t}，合计行=Row {total_row}")
    return out_path
