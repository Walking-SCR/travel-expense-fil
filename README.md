# travel-expense-fill-v3 · 差旅报销单自动生成工具

根据 **携程商旅 PDF**、**打车行程单**、**火车票/大巴票 PDF** 等原始票据，自动生成标准化的差旅费报销 Excel，并自动计算差旅补贴。

## 功能

- 📄 **携程 PDF 解析** — 自动提取出差起止地、起止日期
- 🚕 **打车行程单解析** — Y 坐标分组法精准识别，自动区分差旅/Base地交通
- 🚄 **火车票/大巴票 PDF 解析** — 自动筛选出差区间内的票据
- 💰 **补贴自动计算** — 按城市等级（一类/二类/三类）和住宿标准补贴，周末/加班自动处理
- 🔄 **中断返程检测** — 自动识别出差中途回公司的情况，拆分区间
- 📊 **Excel 自动生成** — 直接操作模板 XML，保留模板原始样式，输出差旅费 + Base地交通费两张表

<img width="1024" height="1024" alt="travel_expense_skill_workflow_1780150157262" src="https://github.com/user-attachments/assets/1498130e-6e77-4ada-8820-392864350c9f" />



## 环境要求

- Python ≥ 3.9
- pip

## 安装

```bash
pip install -r requirements.txt
```

## 初始化配置

首次使用前运行初始化命令，按提示选择模式并配置个人信息：

```bash
python3 scripts/gen_trip_reports.py --init
```

初始化会检查依赖、让你选择执行模式，并生成 `config.json`。

### 执行模式

| 模式 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **CLI 模式** | 一键生成、零交互 | 需提前收集所有参数 | 自动化、Claude Code |
| **Manual 模式** | 逐步确认、灵活调整 | 需多步交互 | 首次使用、不确定参数 |

### `config.json` — 运行配置

控制 PDF 解析方式和图片票据处理策略：

```json
{
  "version": 1,
  "execution_mode": "manual",
  "pdf_parser": {
    "tool": "pymupdf",
    "auto_install": true
  },
  "image_parser": {
    "mcp_available": false,
    "mcp_tool_name": null,
    "fallback_to_manual": true
  }
}
```

| 字段 | 说明 |
|------|------|
| `execution_mode` | `cli` 或 `manual`，由 `--init` 交互选择 |
| `pdf_parser.tool` | PDF 解析引擎（默认 `pymupdf`，首次运行自动安装） |
| `pdf_parser.auto_install` | 是否自动安装 PyMuPDF |
| `image_parser.mcp_available` | 是否配置了图片 MCP 工具（如 MiniMax） |
| `image_parser.mcp_tool_name` | MCP 工具名称 |
| `image_parser.fallback_to_manual` | 无 MCP 时是否降级手动输入金额 |

> 配置文件被 `.gitignore` 排除，修改不会影响仓库。

### `personal_info.json` — 个人信息

```json
{
  "name": "你的姓名",
  "emp_id": "工号",
  "manager": "汇报对象",
  "base_city": "所在城市"
}
```

### `last_trip.json` — 项目信息

每次出差可能不同，运行前根据需要更新：

```json
{
  "project_code": "项目编号",
  "project_name": "项目名称",
  "project_status": "售前",
  "project_manager": "项目经理"
}
```

---

## 在 Claude Code 中使用

本工具可以作为 **Claude Code Skill** 使用，让 Claude 帮你自动完成报销填写。

### 安装方式

将本仓库克隆到 Claude Code 的 skills 目录：

```bash
# 进入 Claude Code skills 目录（如不存在则创建）
mkdir -p ~/.claude/skills/productivity
cd ~/.claude/skills/productivity

# 克隆仓库
git clone https://github.com/Walking-SCR/travel-expense-fil.git
```

### 使用方法

在 Claude Code 对话中，放入出差票据 PDF 文件后，输入以下触发词即可：

> 填写差旅报销
> 报销填写
> 生成差旅费报告

Claude 会自动：
1. 引导你提供项目信息、补贴标准、加班日期等
2. 调用脚本解析 PDF 票据
3. 计算补贴金额
4. 生成标准格式的 Excel 报销单

### 写入 CLAUDE.md 或 settings.json

你也可以在项目级的 `CLAUDE.md` 或 `settings.json` 中注册 trigger 词，让 Claude 自动识别报销任务：

```json
{
  "skills": {
    "travel-expense-fill": {
      "trigger": "填写差旅报销|报销填写|生成差旅费报告|travel-expense"
    }
  }
}
```
## 用法

### 快速入门

准备一个出差目录，放入以下 PDF 文件：

```
2026年04月出差/
├── 202604010001_张三的携程商旅.pdf      # 携程行程单
├── 滴滴出行行程报销单A.pdf               # 滴滴行程单
├── 202604010002_火车票.pdf               # 火车票
└── 202604010003_大巴票.pdf               # 大巴票
```

然后运行：

```bash
python3 scripts/gen_trip_reports.py --dir /path/to/出差目录
```

### CLI 一键生成（推荐）

```bash
python3 scripts/gen_trip_reports.py \
  --dir /path/to/出差目录 \
  --year 2026 --month 4 \
  --non-interactive \
  --standard 1 \
  --overtime-dates 2026-04-09,2026-04-10 \
  --project-code "无" --project-name "无" \
  --project-status "售前" --project-manager "无"
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--dir` | 出差文件所在目录 |
| `--year` / `--month` | 报销归属年月 |
| `--non-interactive` | 非交互模式（跳过确认步骤） |
| `--standard` | 补贴标准：`1` = 公司统一订酒店，`2` = 自行解决住宿 |
| `--overtime-dates` | 加班日期，逗号分隔，如 `2026-04-09,2026-04-10` |
| `--project-*` | 项目信息 |
| `--bus "日期,金额"` | 大巴票补录，如 `--bus "2026-04-10,45.00"` |
| `--train "日期,金额"` | 火车票补录，如 `--train "2026-04-10,74.50"` |
| `--init` | 仅初始化配置 + 检查依赖 |

### 分步手动流程（需逐步确认时）

```bash
# 1. 解析携程 PDF
python3 -c "
from scripts import parse_trip
trips = parse_trip.parse_all_ctrip(['携程1.pdf', '携程2.pdf'], default_year=2026)
print(trips)
"

# 2. 解析火车票/大巴票
python3 -c "
from scripts import parse_ticket
train = parse_ticket.parse_train_ticket('火车票.pdf')
bus = parse_ticket.parse_bus_ticket('大巴票.pdf')
print(train, bus)
"

# 3. 解析打车行程单
python3 -c "
from scripts import parse_didi
didi = parse_didi.parse_all_didi(['滴滴.pdf'], default_year=2026)
merged = [...]  # 上一步携程合并后的区间
classified = parse_didi.classify_didi(didi, merged, '广州')
print(classified)
"

# 4. 填写 Excel（参照 SKILL.md 中 Manual 流程的完整步骤）
```

## 补贴标准

| | 公司订酒店 | 自行解决住宿 |
|---|---|---|
| **一类城市**（北上广深港） | 60元/天 | 220元/天 |
| **二类城市**（省会/计划单列市等） | 50元/天 | 180元/天 |
| **三类城市**（其余） | 40元/天 | 145元/天 |
| **出发日/结束日** | 标准 × 50% | 标准 × 50% |
| **中间周末（无加班）** | 标准 × 50% | 标准 × 50% |
| **中间周末（有加班）** | 标准 × 100% | 标准 × 100% |

## 输出说明

执行后会生成两个 Excel 文件：

- `差旅费-姓名-YYYY年MM月.xlsx` — 差旅费用明细
- `Base地交通费-姓名-YYYY年MM月.xlsx` — Base地交通费用（无数据时跳过）

## 模块说明

| 脚本 | 作用 |
|------|------|
| `parse_trip.py` | 携程 PDF 解析 + 多区间合并 |
| `parse_didi.py` | 打车行程单解析（滴滴 + 通用平台 + 通行费匹配） |
| `parse_ticket.py` | 火车票/大巴票 PDF 解析 |
| `calc_subsidy.py` | 补贴计算 + 加班日期解析 |
| `adjust_trip.py` | 出差区间中断返程检测与拆分 |
| `fill_trip_xlsx.py` | 差旅费 Excel 填写 |
| `fill_base_xlsx.py` | Base地交通费 Excel 填写 |
| `gen_trip_reports.py` | CLI 一键生成入口 |
| `xlsx_edit.py` | Excel XML 底层操作库 |
| `utils.py` | 工具函数 |

## 注意事项

1. **PDF 发票文件**放在一个目录中，脚本会自动发现携程、打车、火车票、大巴票、通行费
2. **图片票据**目前需手动输入金额（通过 `--bus` / `--train` 参数）
3. **项目信息**每次出差可能不同，通过 `--project-*` 参数或更新 `last_trip.json`
4. 详细列映射说明见 `references/column-mappings.md`

## License

内部工具，仅供参考。
