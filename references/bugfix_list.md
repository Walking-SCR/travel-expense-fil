# Bug Fix List (P1~P64)

> ⚠️ 以下是 v3 开发过程中踩到的 bug 及根因。**修改代码时请勿回退这些修复。**

---

### P1：滴滴日期行识别失败 → 城市全为"未知"

**根因**：`_is_date_span` 用 `re.search(r'^\d{2}-\d{2}', text)` 要求从头匹配，但 fitz 提取的 span 文本是 `"12-24 16:28 周"`（前有空格），`^` 永远不匹配。

**修复**：`text.strip()` 后用 `re.search(r'\d{2}-\d{2}\s+\d{2}:\d{2}', t)`（无锚定）。

---

### P2：city_y_map 查询永远返回空 → 城市全为"未知"

**根因**：`_build_city_y_map` 注册 key `("广", "广州市")`，但查询用 `("广州", "广州市")`，key 完全不匹配。

**修复**：抛弃 city_y_map，改用 `_find_city_nearby()` 直接扫描近邻 span（Y 坐标半径 ≤12pt）。

---

### P3：携程目的城市解析失败（PDF 分行格式）

**根因**：PDF 中"目的城市"和"深圳"分行，`r'目的城市\s+(.+)'` 中 `\s+` 不匹配 `\n`。

**修复**：`re.search(r'目的城市\s*\n([^\n]+)', text)` 先行匹配关键词再取下一行。

---

### P4：Base 地 Excel 有旧模板残留数据

**根因**：模板中 Row 9-38 含旧数据，`shutil.copy` 后未清除就写新数据。

**修复**：`fill_base_xlsx` 写数据前调用 `_safe_clear_rows(ws, 9, 38)`。

---

### P5：差旅费 Excel 有旧模板残留数据

**根因**：差旅费模板含 12/1-12/31 的 31 天旧数据，`shutil.copy` 后未清除。

**修复**：`fill_trip_xlsx` 写数据前调用 `_clear_rows(LAST_DATA+1, 41)`。

---

### P6：Base 地合计行位置错误 → 模板公式被覆盖

**根因**：`TOTAL_ROW = 9 + len(sorted_base)` 会覆盖模板合计行 Row 40。

**修复**：合计行固定为 Row 40：`w(TOTAL_ROW, 6, f"=SUM(F{BASE_ROW}:F{38})")`

---

### P7：模板预填旧数据未清除 → _clear_rows 起点太晚

**根因**：差旅费模板本身在 Row 10/14 预填了旧数据（G=74.5/I=47.2 和 G=74.5/I=70.5），`_clear_rows(LAST_DATA+1, 41)` 只清 LAST_DATA 之后，但 LAST_DATA=29 时 Row 10/14 仍未被清除。

**修复**：清除范围改为从 `START_ROW` 开始而非 `LAST_DATA+1`。

---

### P8：滴滴电子发票（无需AI分析）≠ 行程报销单

**根因**："滴滴出行电子发票（无需AI分析）"目录是纯文本格式，`parse_didi.py` 无法解析。

**经验**：行程报销单可解析，电子发票跳过即可。

---

### P9：openpyxl 合并格写入值丢失

**根因**：openpyxl `merge_cells()` 后只有左上角存储实际值，其他单元格变为 `MergedCell` 类型（只读）。

**正确模式**：对合并格次级格写值时先 unmerge → 写左上角 → 不 remerge。

---

### P10：openpyxl 模板 sheet 名与文件名无关

**根因**：Excel 模板的 sheet 名（在 Excel 底部标签页显示）与文件名相互独立。

**修复**：加载模板后必须用 `wb.sheetnames` 确认实际 sheet 名。

---

### P11：模板真实结构（Sheet2 才是数据区，Sheet1 是封面）

**根因**：两个模板都是双 sheet 结构，Sheet1 是封面/说明页，Sheet2 才是真实数据区。

**修复**：总是用 `wb[wb.sheetnames[1]]` 获取数据 sheet。

---

### P14：删除含合并格的行前必须先 unmerge

**根因**：模板 Row11-40 全是 `D{n}:E{n}` 合并格，`delete_rows` 前未取消这些合并格，openpyxl 拒绝删除。

**修复**：`unmerge_cells` 对应的合并格后再 `delete_rows`。

---

### P15：差旅费表头字段写入错误列

**根因**：模板合成格 H2:I2 是标签，J2:M2 才是值位。

**修复**：工号→J2，汇报对象→J3，项目状态→J4，项目经理→J5。

---

### P16：Base地表头字段写入错误列

**根因**：模板 A4:B4 合幵格，A4 是标签，C4 是值位。

**修复**：项目编号→C4，项目状态→E4，姓名→B2，工号→E2。

---

### P17：Base地 Excel 日期列从未写入

**根因**：fill_base_xlsx.py 自 v1 起就没有写入 A 列的代码。

**修复**：`ws.cell(row=row, column=1).value = dt(d.year, d.month, d.day)`。

---

### P18：Base地 D:E 数据行合并格导致列偏移

**根因**：模板数据行 Row9-39 全是 `D{n}:E{n}` 合并格，直接写 D 时被合并格吞掉。

**修复**：写 D/E 前先 unmerge D:E，再分别写 D（目的地）和 E（出差），不 remerge。

---

### P19：模板预填值被 _clear_rows 误清

**根因**：J4="售前"、J5="项目经理（需填写）"是模板预填，_clear_rows 会清空。

**修复**：表头填写完后显式恢复 J4 和 J5。

---

### P20：从模板重建而非原地修复

**根因**：原文件经过多轮修改存在残留值，直接修改可能遗漏。

**策略**：采用从模板复制 + 完整填写的策略，确保无残留。

---

### P24：classify_didi 在真实 PDF 上无法自动分类

**根因**：`_extract_origin_dest()` 在真实 PDF 上未能命中列头关键词。

**修复（手动降级）**：手动构造 `base_amounts` 字典。

---

### P25：A4:B4 合并格锚点是 A4，值位是 C4

**根因**：差旅费模板 Row4 有两套相邻合并格，A4:B4 = 标签，C4:G4 = 值位。

**修复**：项目编号写到 C4 而非 A4。

---

### P27：days_data 缺少 from_city/to_city 导致 B/C/D 列全空

**根因**：调用方只传了 subsidy/day_type 字段，漏了城市字段。

**修复**：构造 days_data 时必须包含 from_city 和 to_city。

---

### P28：execute_code 对 parse_trip ✅ 但对 parse_didi ❌

**根因**：parse_didi.py 在 execute_code 沙盒中报 ModuleNotFoundError。

**推荐策略**：parse_trip + calc_subsidy → execute_code ✅；parse_didi → terminal（更可靠）。

---

### P29：空字符串绕过 `or "售前"` 回退值

**根因**：`pi.get("project_status")` 返回 `""`（而非 `None`），`"" or "售前"` 返回 `""`。

**修复**：统一用 `val if val else "售前"` 显式判断。

---

### P30：Base地合计行 D40:E40 合并格在清空旧数据时被误 unmerge

**根因**：`_safe_clear_rows` 遍历合并格时误伤了合计行 D40:E40。

**修复**：数据行清空范围不包括 Row40，写完后显式恢复合并格和 SUM 公式。

---

### P31：差旅费 E 列事由写死"出差"，未用携程 PDF 实际出差原因

**根因**：fill_trip_xlsx.py 数据行 E 列写死 `"出差"`。

**修复**：从 merged_trips 构造 trip_reason_map 按日期映射出差原因。

---

### P32：差旅费 M 列备注未填补贴标准

**根因**：fill_trip_xlsx.py 从未向 M 列写入补贴标准备注。

**修复**：数据行写入后给 M 列填补贴标准说明。

---

### P34：视觉分析 API 对滴滴 PDF 返回敏感内容错误

**根因**：`mcp_minimax_understand_image` 对滴滴 PDF 报 API Error。

**结论**：不要用视觉分析滴滴 PDF，用 parse_didi.py 解析。

---

### P35：openpyxl `copy.copy(Color)` 丢失 theme 色

**根因**：`copy.copy(Color)` 对 `Color.type='theme'` 无效。

**修复**：用 `ws_template` 克隆方式而非 copy.copy。

---

### P37：`parse_all_ctrip` 参数是 list，`compute_daily_subsidy` 返回 `list[tuple]`

**根因1**：传字符串给 parse_all_ctrip 会被逐字符迭代。
**根因2**：`compute_daily_subsidy` 返回 `list[tuple(date, dict)]` 而非 `(dict, dict)`。

**修复**：传 list 参数，用 list[tuple] 方式解包。

---

### P40：`MergedCell` 只读写入崩溃

**根因**：合并格副格（MergedCell）是只读的，直接写 value 触发 `AttributeError`。

**修复**：克隆循环中检查并跳过 MergedCell。

---

### P41：`didi_trip` 初始值必须是 `{}`，不能用 `0`

**根因**：`didi_trip=0` 是 int，后续 `didi_trip.get(day)` 报错。

**修复**：空 dict 而不是 0；用 `day in didi_trip` 判断而非 `.get(day)`。

---

### P42：`gen_trip_reports.py` 作为推荐入口

从 P42 开始推荐 gen_trip_reports.py 一键生成代替手动步骤。

---

### P43：开放隐藏行替代方案——不动任何合并格

**根因**：unmerge + delete_rows 破坏表头 RichText 富文本。

**修复**：改用 `row_dimensions.hidden` 隐藏多余行（后因 insert_rows 无样式等问题废弃，改用 P45 精准防污染裁剪法）。

---

### P44：合计行起点错误导致误隐藏

**根因**：隐藏行范围起点用 `START + trip_days`——这个位置恰是合计行。

**修复**：从 `START + trip_days + 1` 开始隐藏。

---

### P45：精准防污染裁剪法

**核心逻辑**：表头填值 → 写数据行前 unmerge 合计行合并格 → delete_rows 删除多余行 → 写数据行 → 合计行写入前先清空 → J4/J5 显式恢复。

---

### P46：补贴标准备注写反（220→标准一，110→标准二）

**根因**：代码把补贴金额和标准编号搞反了。

**修复**：standard==2 对应"标准二（自行解决，220元/天）"。

---

### P47：merged_trips 循环解包错误

**根因**：merged_trips 是字典列表，不是元组列表。`for start, end in merged_trips` 触发 ValueError。

**修复**：`for trip in merged_trips: s = trip.get("start")`。

---

### P48：合计行写值前未清空旧值

**根因**：模板合计行合并格中有旧值，写入 None 时 openpyxl 存储为字符串 "None"。

**修复**：写合计行前先清空整行。

---

### P49：J4/J5 模板预填值被 write_val 覆盖

**根因**：`write_val` 传入空值时覆盖了模板预填值。

**修复**：保存前显式恢复 J4="售前"、J5="项目经理（需填写）"。

---

### P50：出差事由硬编码导致所有行都是同一个出差原因

**根因**：事由写死为单一字符串。

**修复**：构造 `trip_reason_map` 按日期映射出差原因。

---

### P51：表头样式（红黑富文本）丢失 —— "只清空不删除不 unmerge"修复

**根因**：`_clear_rows` 中的 unmerge + delete_rows 组合导致表头 RichText 样式漂移。

**修复**：只清空 value，不 unmerge 任何合并格，直接 delete_rows。

---

### P52+54：gen_trip_reports.py 自动处理高铁票+大巴票

v3 新增 CLI 可复用、config.json 配置、MCP 图片优先、PyMuPDF 自动安装。

**图片解析策略**：MCP 工具优先 → 手动输入降级 → 非交互模式跳过。

---

### P60：`fill_trip_xlsx` 的 `bus_fares` 参数被完全忽略

**根因**：fill_trip_xlsx 接受 bus_fares 参数但函数体从未使用。

**修复**：在调用 fill_trip_xlsx **之前**把 bus_fares 合并到 `days_data[d]['bus']`。

---

### P61：多轮生成时 I 列旧值残留

**根因**：I 列写入逻辑是有条件写入（有滴滴才写），无滴滴时跳过导致旧值保留。

**修复**：无论有无滴滴，始终写 I 列（无则写 0 清旧值）。

---

### P62：`XlsxEditor.set_cell_date()` API 陷阱

**根因**：第一个参数是 sheet_index（固定为 2），不是 row。误传 row 导致 KeyError。

**修复**：`ed.set_cell_date(2, f'A{row}', datetime(...))`。

---

### P63：合计行 A32 残留模板旧值"深圳"而非"报销合计"

**根因**：写入合计行 A 列时未正确覆盖模板旧值。

**修复**：用 openpyxl 直接写字符串而非手动 patch XML。

---

### P64：`XlsxEditor` vs openpyxl 使用策略

**推荐**：从模板 `shutil.copy` + openpyxl 完整填写。`XlsxEditor` 对合并格处理不稳定。

**最终推荐流程**：shutil.copy → openpyxl.load_workbook → 写表头→写数据行（无条件写入清旧值）→ 合计行 → 先 unmerge 再 delete_rows → wb.save。

---

### P65：manual 模式缺少中断返程检测步骤（2026-05-21）

**症状**：manual 模式生成的差旅单未识别 4/29 返程，4/30 仍在补贴范围内。

**根因**：Step 7（classify_didi）和 Step 8（加班确认）之间没有调用 `adjust_trip.process_trip_interruptions()`，merged trips 直接进了补贴计算。

**修复**：SKILL.md manual 模式 Step 7 后新增 Step 8（中断返程检测），调 `process_trip_interruptions()` 拆分区间后再执行加班确认和补贴计算。CLI 模式已有（gen_trip_reports.py Step 4d）。

---

### P66：项目信息与个人信息耦合，导致 J5 永远写"项目经理（需填写）"（2026-05-21）

**症状**：用户在 Step 1 提供了项目经理信息，但生成的 Excel J5 列仍然是模板预填值"项目经理（需填写）"。

**根因**：`fill_trip_xlsx.py` 从 `pi`（personal_info.json）读取 `project_manager`，但 personal_info.json 只有 name/emp_id/manager/base_city，不包含项目字段。`pi.get('project_manager')` 永远为 `None`，P49 修复写"项目经理（需填写）"。

**修复**：`fill_trip_xlsx()` 和 `fill_base_xlsx()` 新增 `project_info` 参数，优先从此参数读取项目字段，回退到 `pi`（兼容旧模式）。`gen_trip_reports.py` 新增 `--project-code/--project-name/--project-status/--project-manager` CLI 参数。

---

### P67：Step 1 项目信息确认是文字描述，Hermes 跳过执行（2026-05-21）

**症状**：Hermes agent 没有询问用户是否延用上次项目信息，直接跳过。

**根因**：Step 1 以纯文字描述存在（"读取 last_trip.json，展示上次项目信息，询问用户..."），不是可执行代码块。Hermes 按代码块执行，跳过了文字说明。

**修复**：Step 1 改为 Python 代码块 + AI 代理引导问答。读取 last_trip.json 展示信息后，AI 代理必须主动询问用户是否延用，收集后写入文件。禁止使用 `input()`（agent 环境会崩溃）。

---

### P69：非交互模式默认不提前结束，延伸段残留（2026-05-21）

**症状**：CLI 非交互模式生成的差旅单包含延伸段（如 4/30），用户期望在最后一笔费用日（4/29）结束。

**根因**：`gen_trip_reports.py` 非交互模式下 `answers.append(False)`，`apply_answer` 创建延伸段覆盖 last_return+1 ~ end。

**修复**：改为 `answers.append(True)`，默认提前结束，不生成延伸段。

---

### P70：project_info 多层加载缺失，J5 永远"项目经理（需填写）"（2026-05-21）

**症状**：CLI 和 manual 模式下 J5 列始终显示"项目经理（需填写）"，即使用户想提供项目信息也无法传递。

**根因三合一**：
1. `personal_info.json` 包含 `project_manager: "无"` → P68 过滤逻辑拦截"无" → 显示"项目经理（需填写）"
2. `last_trip.json` key 名不匹配（`project_id` 而非 `project_code`），缺失 `project_status`
3. `gen_trip_reports.py` 只从 CLI 参数和 pi 读取，不查 last_trip.json
4. SKILL.md Step 1 使用 `input()` 在 Hermes 中崩溃，项目信息从未被收集

**修复**：
1. `personal_info.json` 移除 project 字段（项目信息≠个人信息）
2. `gen_trip_reports.py`：三层优先级加载（CLI → last_trip.json → pi），过滤"无"值
3. `last_trip.json`：修正为 `project_code/project_name/project_status/project_manager` 结构
4. SKILL.md Step 1：`input()` 改为 AI 代理问答指令，写入 last_trip.json
5. SKILL.md Step 11：增加 last_trip.json 回退读取
6. SKILL.md 验证清单：J5 不再写死，改为"有则填项目经理名，无则保留模板预填"
