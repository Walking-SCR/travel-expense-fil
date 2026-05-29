# Iteration Log — travel-expense-fill-v3

## v3 → skill-creator 重建（2025-05-14）

### 新增目录结构

按 skill-creator 标准重建：

```
travel-expense-fill-v3/
├── SKILL.md              # 新增 trigger/validator/examples 字段
├── agents/               # 新增（从 skill-creator 复制）
│   ├── grader.md
│   ├── analyzer.md
│   └── comparator.md
├── eval-viewer/          # 新增
│   └── generate_review.py
├── evals/                # 新增
│   └── evals.json        # 3个eval + ground_truth
├── references/
│   └── iteration-log.md  # 本文件
├── scripts/              # 保留（已修复的7个模块）
├── templates/            # 保留
└── assets/               # 新增
    ├── eval_review.html
    └── ground_truth/     # 真实测试数据（eval-0/1/2）
        ├── eval-0/       # 1张携程PDF
        ├── eval-1/       # 2张携程PDF + 2张滴滴
        └── eval-2/       # 1张携程 + 1火车票 + 2滴滴
```

### Bug Fix（本次重建新增）

**P7：模板 Row 10/14 含旧数据，G/I 列残留错误值**

**根因**：`fill_trip_xlsx` 中 `_clear_rows(ws, LAST_DATA+1, 41)` 只清除新数据行之后的旧行，但 `len(days)=20` 时 `LAST_DATA+1=30`，而模板旧数据从 Row 10 就开始了。`Row 10 G=74.5 / I=47.2`，`Row 14 G=74.5 / I=70.5` 未被清除。

**修复**：
```python
# 旧：
_clear_rows(ws, LAST_DATA + 1, 41)
# 新：
_clear_rows(ws, START_ROW, 41)
```
改为从 `START_ROW=10` 开始清除，覆盖所有模板旧数据行。

### 遗留说明

**关于标准选择**：eval 测试中 hardcode `standard=1`，但真实使用需要用户确认。skill 流程中 Step 5 有询问逻辑（选择标准一/二），但在自动化测试场景无法确认，需要手动指定。

**关于 ground truth 数据集**：eval-0/1/2 的测试数据来自真实12月出差文件，数据本身是用户的真实报销记录。ground truth 基于当前 v3 脚本的正确输出，手工验证确认。

---

## v11 — 方案二表头样式备份修复 + 视觉分析降级（2026-05-19）

### fill_trip_xlsx.py（v11-scheme2）

**问题**：`trip_days < 31` 时，`delete_rows` 物理删除多余行导致 Row 2~5 表头红色字体颜色漂移（变黑）。

**修复**：物理删除前备份关键单元格 font/fill，删除后还原：

```python
# ══ 三、动态行数（物理删除前备份表头样式）══
# 1. 备份
header_cells = ["A2","H2","A3","H3","A4","H4","A5","H5","A6"]
header_styles = {cell: (ws[cell].font, ws[cell].fill) for cell in header_cells}

if trip_days < 31:
    for row in range(TRIP_START + trip_days, TRIP_END + 2):
        for mr in list(ws.merged_cells.ranges):
            if mr.min_row <= row <= mr.max_row:
                try: ws.unmerge_cells(str(mr))
                except: pass
    ws.delete_rows(TRIP_START + trip_days, TRIP_END - (TRIP_START + trip_days) + 1)
elif trip_days > 31:
    for _ in range(trip_days - 31):
        ws.insert_rows(TRIP_START + 31)

# 2. 还原
from copy import copy
for cell, (font, fill) in header_styles.items():
    if font: ws[cell].font = copy(font)
    if fill: ws[cell].fill = copy(fill)
```

### fill_base_xlsx.py（v11-scheme2）

**修复**：双重循环备份 Row2~6 全列（A~G）font/fill：

```python
# 1. 备份 Row2~6 所有单元格
header_styles = {}
for r in range(2, 7):
    for c in range(1, 8):
        cell = ws.cell(row=r, column=c)
        header_styles[(r, c)] = (copy.copy(cell.font), copy.copy(cell.fill))

# 2. 物理删除/插入行...

# 3. 还原
for (r, c), (font, fill) in header_styles.items():
    target_cell = ws.cell(row=r, column=c)
    if font: target_cell.font = font
    if fill: target_cell.fill = fill
```

### P34：视觉分析 API 对滴滴 PDF 返回敏感内容错误（2026-05-19 实测）

**症状**：`mcp_minimax_understand_image` 对两个滴滴行程单 PDF 均返回：
```
API Error: 1026-input new_sensitive, input image sensitive
```

**结论**：视觉模型会扫描 PDF 内容检测敏感信息，即使内容是普通行程单也可能触发。**不要用视觉分析滴滴 PDF**。

**推荐工作流（已验证）**：
1. `parse_didi.py`（execute_code/terminal）提取金额和日期 ✅
2. `classify_didi()` 分类出差地 vs Base 地 ✅
3. `from/to` 降级：直接用 `fitz` + 坐标提取法（terminal）从 PDF span 数据中提取列头 `起点`/`终点` 近邻的地址
4. 滴滴 PDF 地址格式：`"石井|美宜佳(浅水路店)"`，构造 base_amounts 时将 `|` 替换为简洁描述

---

## v8 — 模板真实结构重写（2026-05-15）

### 核心发现

两个模板都是**双 sheet 结构**：
- `差旅费-template.xlsx`：Sheet1=封面，Sheet2("差旅")=数据区
- `Base地交通费-template.xlsx`：Sheet1=封面，Sheet2("Base地交通费")=数据区

加载模板后必须用 `wb.sheetnames` 确认实际 sheet 名，不能假设 sheet 名=文件名。

### 关键列映射修正

**差旅 Sheet2 表头（Row2-5）**：
- H:I 合并格中，**H 列才是值位**（openpyxl 报告 I2 是 MergedCell 是误报）
- 表头值写入 H 列（H2=工号，H3=汇报对象，H4=项目状态，H5=项目经理）

**Base地 Sheet2 表头（Row2-5）**：
- B:C 合并格中，**B 列是值位**（openpyxl 报告 C2 是 MergedCell）
- E:F 合并格中，**E 列是值位**（openpyxl 报告 F2 是 MergedCell）

### 关键 Bug 修复

**P13**：write_val 空字符串清空模板已有内容
- `write_val(ws, 2, '', 8)` → H2 标签 `'* 工号'` 被清空
- 修复：`if not val and val != 0: return None`

**P14**：删除含合并格的行前必须先 unmerge
- 修复：先遍历所有合并格取消涉及目标行的，再 delete_rows

### P12（从 SKILL.md 补录）：动态行数调整逻辑

**业务规则**：
- `base_days < 31` → 删除多余行（保留合计行）
- `base_days == 31` → 不调整
- `base_days > 31` → 在合计行前插入 `base_days - 31` 行

### 脚本版本

- `fill_trip_xlsx.py` → v8：write_val 空值跳过；表头写入 H 列；合并格安全删除
- `fill_base_xlsx.py` → v8：数据行 D:E 先 unmerge 再分别写，不 remerge
