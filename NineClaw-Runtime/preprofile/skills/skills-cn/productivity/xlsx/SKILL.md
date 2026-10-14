---
name: xlsx
description: "创建、读取和编辑 Excel .xlsx 电子表格及 CSV 文件。"
version: 1.0.0
author: Anthropic (adapted by Nous Research)
license: Proprietary. LICENSE.txt has complete terms
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Excel, XLSX, Spreadsheets, Office, Productivity]
    category: productivity
    related_skills: [docx, pdf, powerpoint]
---

# XLSX 技能

创建、读取和编辑 Excel 工作簿，包括公式、格式、图表、数据清理和格式转换。交付前，所有包含公式的输出都必须完成重新计算且不存在错误。

## 适用场景

只要电子表格文件是主要输入或输出，就应使用此技能：打开、读取、编辑或修复现有的 .xlsx、.xlsm、.xltx、.csv 或 .tsv 文件；从零开始或基于其他数据创建新电子表格；在表格格式之间转换；将杂乱的表格数据清理成规范的电子表格。每当用户提及电子表格的文件名或路径时，即使只是随口提到，也应触发此技能。如果交付物是 Word 文档（使用 `docx` 技能）、HTML 报告、独立脚本或 Google Sheets API 集成，则不要触发。对于金融级建模规范（DCF、LBO、三表模型），可选的 `excel-author` 技能会在本技能基础上增加更严格的标准。

## 前置条件

```bash
pip install openpyxl pandas "markitdown[xlsx]"
which soffice || sudo apt install -y libreoffice   # formula recalculation (scripts/recalc.py)
```

macOS：`brew install libreoffice`。

## 快速参考

| 任务 | 方法 |
|---|---|
| 使用公式/格式进行**创建**或**编辑** | `openpyxl` — 参见下文的注意事项 |
| 批量导入或导出**数据** | `pandas`（`read_excel`、`to_excel`） |
| **快速查看**工作表 | `markitdown file.xlsx` — 每个工作表对应一个 `## SheetName`；也可读取 `.xlsm`。它不提供单元格坐标，因此不要据此规划编辑。（`read_file` 也会自动提取 .xlsx 内容） |
| **读取**模型（公式*及*数值） | 执行两次 `load_workbook` — 参见注意事项 |

> 下文中的脚本路径均相对于本技能目录。

## 每项输出都必须满足的要求

- 除非用户另有要求，否则全文使用**专业字体**（Arial、Times New Roman）。
- **公式错误必须为零。** 当 `recalc.py` 报告 `errors_found` 时，绝不能交付。如果你认为某个错误在你操作前就已存在，请证明这一点：用 `data_only=True` 加载*原始文件*并检查该单元格。你引入的错误与继承来的错误看起来完全一样。
- **使用公式，绝不硬编码结果。** 应写入 `sheet['B10'] = '=SUM(B2:B9)'`，而不是由 Python 计算出的合计值。输入变化时，工作表必须能重新计算。
- **严格遵循用户的规格。** 工作表名称、列标题以及用户明确给出的公式都必须完全一致。无论设计多么优雅，只要重新设计后计算的是其他内容，就算失败。
- 在读者可见的位置**记录每项假设和每个硬编码数字**，例如单元格批注，或表格末尾的相邻单元格。有真实来源时应引用；数字来自用户时，也要如实注明。
- **你创建并供他人填写的工作簿**需要一份简短的填写说明，指出应编辑哪些单元格，并提供一行使用真实合理数值的示例，以展示预期格式。若任务是编辑现有文件，绝不要添加这样的示例行。
- **编辑现有文件时，必须完全遵循其既有惯例。** 这些惯例优先于此处所有指南。先找出指定的输入单元格——通常会以不同的字体颜色、填充色或底纹标示——只在这些单元格中写入，并保持所有现有公式不变。

## 重新计算（文件包含公式时必须执行）

openpyxl 会将公式写成字符串，且**不包含缓存值**。在重新计算之前，任何读取缓存值的工具都会把所有公式单元格读成 `None`，包括 `pandas`、`load_workbook(data_only=True)` 以及大多数预览工具。

```bash
python scripts/recalc.py output.xlsx [timeout_seconds]   # default 30
```

LibreOffice 会计算每个公式，文件将被**原地重写**，并返回 JSON：`status`（`success` | `errors_found`）、`total_formulas`、`total_errors`，以及按错误类型列出至多 100 个单元格的 `error_summary`（`locations_truncated` 表示省略了多少个位置——应以 `total_errors` 为准，而不是列表长度）。修复其中列出的错误，然后再次运行。**如果 JSON 包含 `error` 键而不是 `status`，说明根本没有执行重新计算**；也只有这种情况会以非零状态退出。`errors_found` 的退出状态为 0，因此绝不能把正常退出当作工作簿无误的证明。

**重新计算结果为绿色，只能证明公式能够*求值*，不能证明公式*正确*。** 范围偏差一行或引用了错误行，都可能生成没有报错但数值错误的文件。在展开构建整个网格之前，先写 2–3 个公式，并检查它们是否取到了预期值。

**如果工作簿链接到其他文件，使用 openpyxl 重新保存后再重新计算会丢失这些链接。** 这类公式形如 `='[1]Returns Analysis'!$B$2`；其中 `[1]` 是工作簿外部引用列表中的索引，指向磁盘上的*另一个文件*，而不是某个工作表。该文件通常并不存在，因此单元格中的缓存值是保留其数据的唯一依据。openpyxl 保存时会移除该值；随后 LibreOffice 必须真正解析该引用，但会失败、写入 `#NAME?` 并删除所有链接。在这种状态下，`recalc.py` 会拒绝运行——覆盖保存前，应先从原始文件中复制这些单元格的值（`--force` 可强制覆盖，但也表示接受链接丢失）。

## 选择能够通过验证的公式

LibreOffice 实现的函数少于 Excel；任何它无法求值的函数，都会在交付文件中固化为字面量 `#NAME?`。

- **优先使用 Excel 2007 时代的函数**，例如 `SUMIFS`、`INDEX`、`MATCH`、`IFERROR`、`SUMPRODUCT`；这些函数不需要前缀。
- **有六个 2007 年后的函数可用，但必须带 `_xlfn.` 前缀**。这是因为 openpyxl 会逐字将公式写入 XML，而 Excel 在存储 2007 年后的函数名时会添加此前缀（其界面会隐藏前缀）：`_xlfn.TEXTJOIN`、`_xlfn.CONCAT`、`_xlfn.IFS`、`_xlfn.SWITCH`、`_xlfn.MAXIFS`、`_xlfn.MINIFS`。如果不带前缀，每个函数都会产生 `#NAME?`。
- **绝不要使用 `XLOOKUP`、`XMATCH`、`SORT`、`FILTER`、`UNIQUE` 或 `SEQUENCE`。** LibreOffice 无法可靠地对它们求值；即使较新的版本支持，这些也是溢出数组函数，而由 openpyxl 写入的文件不含溢出元数据，因此范围内只有左上角单元格会得到值——而面对这种截断结果，`recalc.py` 仍会报告 `total_errors: 0`。查找请使用 `INDEX`/`MATCH`，排序、筛选和去重则应在 Python 中完成后再写入单元格。
- LibreOffice 无法解析的公式在写回时会变成**小写**；若旁边同时出现 `#NAME?`，这是一个快速判断信号。

## openpyxl 注意事项

- **读取模型需要加载两次。** `data_only=True` 会返回缓存值，但公式会消失；默认模式会返回公式字符串，但没有数值。一次加载无法同时得到两者。
- **如果保存，`data_only=True` 具有破坏性。** 该工作簿中已不再有公式，保存会用字面值替换所有公式，而且无法恢复。
- **对刚由 openpyxl 写入的文件使用 `data_only=True`，所有位置都会返回 `None`**；请先运行 `recalc.py`。（结果为 `""` 的公式同样会读成 `None`。）
- **合并单元格：只能写入左上角的锚点单元格。** 区域中的其他每个单元格都是 `MergedCell`，其 `.value` 为只读。
- **`.xlsm` 会丢失宏，除非传入 `keep_vba=True` 给 `load_workbook`。**
- **名称中含空格的工作表，在跨表引用时必须加引号：** `='Assumptions Inputs'!$B$5`。不加引号会计算为 `#VALUE!`。

## 财务模型

除非用户另有要求，或现有文件已经采用其他规则。

**颜色：**硬编码输入和情景调节项使用蓝色文字（`0,0,255`）· 公式使用黑色 · 指向另一工作表的链接使用绿色（`0,128,0`）· 指向另一文件的链接使用红色（`255,0,0`）· 关键假设和需要用户填写的单元格使用黄色填充（`255,255,0`）。

**数字：**货币格式为 `$#,##0`，并在标题中注明单位（`Revenue ($mm)`）· 零值显示为 `-`，百分比中的零也一样（`$#,##0;($#,##0);-`）· 负数使用括号 · 百分比格式为 `0.0%`，并且**以小数形式存储**（`0.15` 显示为 `15.0%`；存储 `15` 则显示为 `1500.0%`）· 估值倍数格式为 `0.0x` · 年份存为文本（`"2024"`，绝不能是 `2,024`）。

**结构：**每项假设都应放在独立且带标签的单元格中，并由使用它的公式引用（`=B5*(1+$B$6)`，绝不能写成 `=B5*1.05`）· 所有预测期间的公式必须保持一致，因为行中间单独被编辑的单元格是最常见的隐蔽错误 · 对可能为零的分母进行防护。

如需完整的投资银行建模规范（平衡检查、敏感性分析表、命名区域），请安装可选技能：`hermes skills install official/finance/excel-author`。

## 验证

1. `python scripts/recalc.py output.xlsx` → `status: success`、`total_errors: 0`。
2. 重新计算后，使用 `load_workbook(data_only=True)` 抽查 2–3 个计算单元格，并与预期值核对。
3. 运行 `markitdown output.xlsx`，检查是否有缺失的工作表、错位的标题或遗留的占位符。

## 相关技能

`docx`（Word 文档）、`pdf`（PDF 工作）、`powerpoint`（演示文稿），以及可选的 `excel-author`（金融级建模标准）。
