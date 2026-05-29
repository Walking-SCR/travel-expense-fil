# 模板精确列映射（2026-05-21 实测修正版 v16）

> ⚠️ **2026-05-21 修正**：差旅费模板 Row4-5 合并格为 `C4:G4` 和 `C5:G5`，项目编号/项目名称值写入 `C4`/`C5`（实测确认）。Base地模板为「招待费」类型，不含姓名/工号字段。

## 差旅费模板 Sheet2 "差旅"

### 表头合并格（Row2-5）

| 字段 | 正确列号 | 写入坐标 | 说明 |
|------|---------|---------|------|
| 姓名 | **C2** | `ws.cell(2, 3)` | C2:G2 合并格锚点 |
| 工号 | **J2** | `ws.cell(2, 10)` | J2:M2 合并格值位 |
| 汇报对象 | **J3** | `ws.cell(3, 10)` | J3:M3 合并格值位 |
| 项目编号 | **C4** | `ws.cell(4, 3)` | C4:G4 合并格次级格（实测确认，2026-04） |
| 项目状态 | **J4** | `ws.cell(4, 10)` | J4:M4 合并格，已有"售前"预填 |
| 项目名称 | **C5** | `ws.cell(5, 3)` | C5:G5 合并格次级格（实测确认，2026-04） |
| 项目经理 | **J5** | `ws.cell(5, 10)` | J5:M5 合并格，已有"项目经理（需填写）" |
| J4 预填 | "售前" | — | 模板已有，**不清** |
| J5 预填 | "项目经理（需填写）" | — | 模板已有，**不清** |

### 数据列（A=日期，B~L=各项费用）

| 列 | 内容 | 写入 |
|----|------|------|
| A | 日期 | 写 Excel 序列号：`int((datetime - datetime(1899,12,30)).days)` |
| B | base城市 | 写 `from_city` |
| C | 出发地 | 写 `from_city` |
| D | 出差地 | 写 `to_city` |
| E | 事由 | 写 `reason`，设置 `wrap_text=True` |
| F | 机票 | 写 `plane` 或 0 |
| G | 高铁/动车 | 写 `train_fares.get(day, 0)` |
| H | 大巴/轮船 | 写 `bus` 或 0 |
| I | 目的地交通费（滴滴） | 写 `didi_trip.get(day, 0)`（无滴滴也写0） |
| J | 住宿 | 写 `hotel` 或 0 |
| K | 当日补贴 | 写 `subsidy` |
| L | 报销合计 | 写 `bus + didi + subsidy` |
| M | 备注 | 写补贴标准说明，设置 `wrap_text=True` |

### 合计行（Row = 10 + trip_days）

| 列 | 公式 |
|----|------|
| G (7) | `=SUM(G10:G{last})` |
| H (8) | `=SUM(H10:H{last})` |
| I (9) | `=SUM(I10:I{last})` |
| K (11) | `=SUM(K10:K{last})` |
| L (12) | `=SUM(L10:L{last})` |

> ⚠️ **合计行写入前只清要写的列**：只清 `[1,7,8,9,11,12]`，跳过他格（合计行可能是合并格）。

---

## Base地交通费模板 Sheet2 "Base地交通费"

> 当前 `fill_base_xlsx.py` 会填写表头项目信息和数据行；本文件只作为维护脚本时的列坐标参考。

### 数据列（Row9=起始，固定）

| 列 | 内容 | 写入方式 |
|----|------|---------|
| A | 时间 | `ws.cell(row, 1).value = datetime_obj` |
| B | 出发地 | 写 `info.get("from")` 或 `"家"` |
| C | 目的地 | 写 `info.get("to")` 或 `"广州白云站"` |
| D | 事由（合并格 D:E） | 先取消模板预置合并格，再写 D=行程 |
| E | 留空 | 不写 |
| F | 费用 | `round(amount, 2)` |

> 当前脚本会重新合并数据行的 `D{n}:E{n}`，让事由保持跨列显示。

### 合计行（Row = 9 + base_days）

| 列 | 公式 |
|----|------|
| F (6) | `=SUM(F9:F{last})` |

---

## 脚本修复对照表

### fill_trip_xlsx.py（当前版本）

| 问题 | 正确写法 |
|------|---------|
| 工号写入 | `ws.cell(2, 10).value = pi["emp_id"]`（J列，不是I列） |
| 汇报对象写入 | `ws.cell(3, 10).value = pi["manager"]` |
| 项目编号写入 | `ws.cell(4, 3).value = pi.get("project_code") or "无"`（C4，不是A4） |
| 项目状态写入 | `v = pi.get("project_status"); ws.cell(4, 10).value = v if v else "售前"` |
| 项目经理写入 | `pm = pi.get("project_manager"); ws.cell(5, 10).value = pm if pm else "项目经理（需填写）"` |
| 项目名称写入 | `ws.cell(5, 3).value = pi.get("project_name") or "无"`（C5，不是A5） |
| 出差事由 | 用 `trip_reason_map` 按日期映射 |
| M列补贴备注 | `standard==2 → "选择补贴标准二（自行解决，220元/天）"` |
| I列滴滴 | 无滴滴也写 0（清旧值） |
| 合计行清空 | 只清要写的列，跳过合并格 |
| merged_trips 循环 | `for trip in merged_trips: s=trip.get("start")`（字典列表，不是元组） |

### fill_base_xlsx.py（当前版本）

| 问题 | 正确写法 |
|------|---------|
| 表头 | 写姓名、工号、汇报对象、项目编号、项目状态、项目名称、项目经理 |
| 日期A列 | `ws.cell(row, 1).value = date_obj` |
| 出发地B列 | 写 `info.get("from")` |
| 目的地C列 | 写 `info.get("to")` |
| D:E合并格 | 先 `unmerge`，写 D=行程，再按当前脚本重新合并 |
| 合计行 | `ws.merge_cells(f"D{total}:E{total}")`；`ws.cell(total,6)=f"=SUM(F9:F{last})"` |

---

## 已知陷阱

| 编号 | 描述 | 状态 |
|------|------|------|
| P46 | 补贴标准二/一 写反 | ✅ 已修复 |
| P47 | merged_trips 解包格式错 | ✅ 已修复 |
| P48 | 合计行合并格写 None 变字符串 | ✅ 已修复 |
| P49 | J5 预填值被 "无" 覆盖 | ✅ 已修复 |
| P50 | 出差事由硬编码 | ✅ 已修复 |
| P51 | 表头 RichText 丢失 | ✅ 只清空不 unmerge 方案 |
| P52 | Base地模板列映射错误（招待费类型） | ✅ 已修正 |
| P54 | 差旅费：项目编号/名称列映射错误（A4→C4、A5→C5） | ✅ 2026-04 实测确认 |
