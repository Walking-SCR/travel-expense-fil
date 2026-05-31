"""
fill_base_xlsx.py — 填写 Base 地交通费 Excel（xlsx_edit 重写版）

直接用 xlsx_edit 操作 XML，不走 openpyxl save，
100% 保留模板原始结构（namespace、phoneticPr、calcChain.xml、mergeCells 等）。

支持同日多笔行程（base_amounts[d] 为列表时每条独立成行）。
"""
import sys
from datetime import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from xlsx_edit import XlsxEditor
from utils import get_template


def fill_base_xlsx(out_path, base_amounts, pi, project_info=None):
    """填写「Base地交通费」Excel。

    base_amounts 支持两种格式：
      - 旧格式: {date: {"amount": x, "from": x, "to": x}}
      - 新格式: {date: [{"amount": x, "from": x, "to": x}, ...]}
    """
    if not base_amounts:
        print("ℹ️ 无Base地打车行程，跳过生成Base地交通费表格")
        return None

    template_path = get_template("Base地交通费-template.xlsx")
    ed = XlsxEditor(template_path, out_path)
    ed.load()

    # 项目信息：优先 project_info，回退到 pi
    pj = project_info or pi

    BASE_ROW = 9

    # ── 展平为 entries 列表 ──
    entries = []
    for d in sorted(base_amounts.keys()):
        val = base_amounts[d]
        if isinstance(val, list):
            for info in val:
                entries.append((d, info))
        else:
            # 兼容旧格式
            entries.append((d, val))

    total_entries = len(entries)
    total_row = BASE_ROW + total_entries

    # ══ 一、表头填写 ══
    ed.set_cell_text(2, 'B2', pi.get('name') or '无')
    ed.set_cell_text(2, 'E2', pi.get('emp_id') or '无')
    ed.set_cell_text(2, 'E3', pi.get('manager') or '无')
    ed.set_cell_text(2, 'B4', pj.get('project_code') or '无')
    ed.set_cell_text(2, 'E4', pj.get('project_status') or '无')
    ed.set_cell_text(2, 'B5', pj.get('project_name') or '无')
    ed.set_cell_text(2, 'E5', pj.get('project_manager') or '无')

    # ══ 二、清除数据区域所有 D:E 合并（模板预置了 D9:E9~D40:E40）══
    for row in range(9, 41):
        ed.unmerge_cells(2, f'D{row}:E{row}')

    # ══ 三、清数据行（9-40，含合计行 40）══
    ed.clear_rows(2, BASE_ROW, 40)

    # ══ 四、填数据行 ══
    for i, (d, info) in enumerate(entries):
        row = BASE_ROW + i

        ed.set_cell_date(2, f'A{row}', dt(d.year, d.month, d.day))
        ed.set_cell_text(2, f'B{row}', info.get('from') or '无')
        ed.set_cell_text(2, f'C{row}', info.get('to') or '无')
        ed.set_cell_text(2, f'D{row}', '出差高铁站打车费')
        # E 列在模板上属于 D:E 合并格的从格，不写值
        ed.set_cell_number(2, f'F{row}', round(float(info.get('amount', 0)), 2))

        # D:E 合并（事由不拆格）
        ed.merge_cells(2, f'D{row}:E{row}')

    # ══ 五、自动换行 + 自适应行高（数据行整行）══
    for i in range(total_entries):
        row = BASE_ROW + i
        for col in ('A', 'B', 'C', 'D', 'E', 'F'):
            ed.set_cell_wrap(2, f'{col}{row}')
        ed.set_row_auto_height(2, row)

    # ══ 六、合计行（先写在模板 Row 40，delete_rows 会重编号到 total_row）══
    ed.set_cell_text(2, 'A40', '合计')
    ed.set_cell_formula(2, 'F40', f'=SUM(F{BASE_ROW}:F{BASE_ROW + total_entries - 1})')
    ed.merge_cells(2, 'D40:E40')

    # ══ 七、删除多余行（重编号合计行 40 → total_row）══
    if total_entries < 31:
        ed.delete_rows(2, BASE_ROW + total_entries, 40 - (BASE_ROW + total_entries))

    ed.strip_calc_chain()
    ed.flush_all()
    print(f"✅ Base地交通费已生成: {out_path}")
    print(f"   行程数={total_entries}，数据行={BASE_ROW}~{BASE_ROW+total_entries-1}，合计行=Row {total_row}")
    return out_path
