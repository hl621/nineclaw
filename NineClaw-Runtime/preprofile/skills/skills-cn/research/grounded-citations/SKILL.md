---
name: grounded-citations
description: "让回答和文档以带引用、可验证的来源为依据。"
version: 1.1.0
author: Hermes Agent + Teknium
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Citations, Grounding, Sources, Web, Reports]
    category: research
    related_skills: [research-paper-writing, arxiv, ocr-and-documents]
---

# 有据可查的引用

每项取自外部来源的论断，都要配上内联编号引用和一份 Perplexity 风格的
`Sources:` 列表。由台账脚本掌管 `url → [n]` 映射，因此编号和 URL 来自检索，
绝不依赖记忆——模型只会输出已提供给它的小整数。

对于高风险工作，同一份台账还可充当事实核查链：为每个来源附上逐字引文
（除非引文确实出现在抓取的页面文本中，否则会被拒绝），源自模型知识的论断
标记为 `[unverified]`，而当草稿引用的来源没有证据时，`verify --evidence`
会令验证失败。

本技能适用于聊天回答、书面文档（markdown、PDF、docx、幻灯片）和研究报告。
它不涵盖学术 BibTeX 流程——会议论文请使用 `research-paper-writing` 技能，
本技能可为其提供输入（参见 `references/citation-formats.md`）。

## 何时使用

只要回答或产物所依据的是你检索到、而非原本就知道的信息，就应使用：

- 研究、比较、新闻摘要、“X 的当前状况如何”
- 任何写入磁盘且引用、转述或报告外部事实的交付物——报告、简报、文档、
  演示文稿、Wiki 页面
- 用户希望核查你工作的事实查找任务
- 必须明确归属相互冲突来源的多来源综合

如果检索只是另一项任务中的附带环节，则跳过内联引用——例如编程途中快速查询
语法/版本、闲聊或创意写作。只有当用户确实可能需要链接时，才提及 URL。

## 前置条件

除标准工具集外无需其他条件。`scripts/sources.py` 是仅使用标准库的 Python 3
脚本。检索可来自任何已配置方式：`web_search`、`web_extract`、
`browser_navigate` 或 `terminal`（curl、CLI）。

台账位置：`$HERMES_HOME/cache/citations/ledger.json`（按 profile 隔离）。
可按任务使用 `--ledger <path>` 或 `HERMES_CITATION_LEDGER` 覆盖。

## 如何运行

```bash
S=~/.hermes/skills/research/grounded-citations/scripts/sources.py

python3 "$S" reset                                  # start a clean ledger
python3 "$S" add https://example.com/a --title "A"  # prints: [1]
python3 "$S" add https://example.com/b --title "B"  # prints: [2]
python3 "$S" list                                   # ledger table
python3 "$S" render                                 # Sources: block
python3 "$S" verify draft.md                        # catch bad citations
```

`add` 具有幂等性，并会对 URL 进行规范化：在同一份台账中，相同页面始终返回相同
id，因此经过多轮搜索/提取后，id 仍保持稳定。

## 快速参考

| 操作 | 命令 |
|---|---|
| 为新任务创建全新台账 | `sources.py reset` |
| 登记一个来源并获取其 id | `sources.py add <url> [--title T]` |
| 一次登记多个来源 | `sources.py add <url1> <url2> ...` |
| 从工具的 JSON 输出中登记 | `sources.py ingest results.json` |
| 为来源附上逐字证据 | `sources.py quote <id> --text "exact wording" --from page.txt` |
| 显示台账 | `sources.py list [--json]` |
| 渲染 Sources 区块 | `sources.py render [--style markdown\|plain\|footnotes\|bibtex\|evidence] [--only 1,3]` |
| 仅渲染草稿实际引用的来源 | `sources.py render --cited-in draft.md` |
| 就地重写草稿的 Sources 区块 | `sources.py render --replace-in draft.md` |
| 检查草稿中的引用 | `sources.py verify draft.md [--strict] [--min-coverage 0.6] [--evidence]` |

## 操作流程

① 对于将产出有来源依据的回答或文档的任务，开始时应**重置台账**。若是继续处理
已有草稿且其中已经包含 id，则不要重置——复用台账能保持编号稳定。

② **在检索时登记每一个来源。** 每次执行 `web_search` / `web_extract` /
`browser_navigate` / fetch 后，将 URL 传给 `sources.py add`（或将原始 JSON
通过管道传给 `sources.py ingest`）。务必在撰写正文*之前*完成。事后凭记忆登记，
正是本技能旨在防止的失败模式。

③ **边写边引用。** 在来源所支持的每个句子后，紧接着放置带方括号的 id：

```
Ice floats because it is less dense than liquid water.[1][2]
```

- 方括号前不要留空格；每个 id 各用一对方括号。
- 每句最多 3 个 id。逐句引用，不要在末尾集中堆放引用。
- 只能使用台账返回的 id。绝不虚构 id 或 URL。
- 来自你自身知识的论断不加引用。
- 来源冲突时：呈现双方观点，并分别附上各自的 id。
- 数字、日期和名称须按来源中的原文准确引用；对缺口要明确标注
  （“未找到 X 的来源”），不要含混带过。

④ 使用 `sources.py render --cited-in <draft>` **附加 Sources 区块**，使
id → URL 映射由台账自动生成，而不是手工重输。对于非 Markdown 目标，选择匹配的
`--style`，并遵循 `references/citation-formats.md` 中的放置方式（docx 使用脚注，
PDF/LaTeX 使用尾注，演示文稿添加 Sources 幻灯片，Wiki 输出按页列出来源）。

⑤ **交付前验证**——`sources.py verify <draft>` 遇到未知 id、Sources 区块与台账
不一致，或（使用 `--min-coverage` 时）正文引用过于稀疏，都会以非零状态退出。
修复后重新运行。

⑥ **聊天回答**遵循相同步骤，只是草稿位于回复中：登记来源、添加内联引用，并以
渲染出的 `Sources:` 列表结尾。对于简短回答，可以使用
`sources.py render --only <ids>` 渲染区块，无需写入文件。

## 事实核查模式

对于读者必须能够核查证据链的工作——医疗、法律、金融、安全、争议性论断，或用户
明确要求事实核查时——应从“引用”升级为“证据”：

① **为每个来源附上一段逐字引文。** 提取页面后，将其文本保存到文件，并附上承载
每项论断的句子：

```bash
python3 "$S" quote 1 --text "Ice is about 9% less dense than liquid water." --from page1.txt
```

除非引文逐字出现在证据文本中，否则会被拒绝（匹配时忽略空白、大小写和 Markdown
标记——提取文本中的 `_[ERAP1](https://…)_` 等内联链接可匹配读者看到的纯文本），
因此，转述内容或记错的数字无法伪装成证据。请从抓取的文本中复制粘贴，绝不要
重新输入。引用读者实际看到的句子——匹配器会替你穿透提取器的标记，因此无需在
引文中复现链接语法或转义星号。

② **使用 `[unverified]` 标记模型知识论断。** 无法找到来源但对结论至关重要的论断，
应以明确标记代替引用：

```
The refactor likely predates the 2.0 release.[unverified]
```

`verify --min-coverage` 会将带 `[unverified]` 的句子计为已覆盖——目标是为每项
论断声明出处，而不是每句都添加引用。若关键论断可以核查，就应核查；
`[unverified]` 只用于确实无法核查的内容。若一份事实核查交付物主要由
`[unverified]` 标记构成，应在摘要中明确说明。

③ **用第二个独立来源交叉核查争议事实。** 当两个来源不一致时，用各自的 id 和
引文分别引用双方观点，并说明你更看重哪一方及原因。一个来源只能算报道；两个
独立来源才构成交叉印证。

④ **使用证据关卡验证并渲染证据区块：**

```bash
python3 "$S" verify report.md --evidence --min-coverage 0.5
python3 "$S" render --style evidence --replace-in report.md
```

若任一已引用来源没有附加引文，`--evidence` 会令草稿验证失败。`evidence` 渲染
样式会在每个来源的 URL 下方打印其引文，使交付物呈现“论断 → 来源 → 精确支撑文本”
的完整链条，无需读者凭空相信任何内容。使用 `--replace-in <draft>` 就地重写已有
Sources 区块（具有幂等性——附加更多引文后可安全地重新运行）；`--cited-in` 则改为
打印到 stdout。两者都会生成标题 `## Sources`（`--style plain` 生成
`Sources:`）。

**`--min-coverage` 的统计方式。** 覆盖率为
`sentences with declared provenance / prose sentences`。正文句子是 Sources 区块
之后由 4 个以上单词构成的非空行片段；标题（`#`）、表格行（`|`）和围栏代码会被
排除，块引用标记则会被剥离。出处可由 `[n]` 引用或 `[unverified]` 标记声明，
因此同时含有两者的句子只计一次。先运行不带阈值的 `verify`，读取
`info: stats:` 行查看计数，再选择数值。

## 常见陷阱

- **写完后才登记。** 台账必须根据工具输出填充，不能从草稿中反向重建——后者会
  再次引入编号本已消除的 URL 幻觉风险。
- **任务中途重新编号。** 绝不要手工编辑草稿中的 id。id 是台账中的身份标识；
  如果草稿引用 `[4]`，`[4]` 就必须始终对应那个来源。只在任务之间运行 `reset`。
- **把 URL 重新输入 Sources 区块。** 始终使用 `render`。手工输入的 URL 本身就是
  未验证的论断。
- **把搜索摘要当成已读页面来引用。** `web_search` 的描述只能支撑其逐字陈述的内容。
  当论断需要页面正文支撑时，应引用提取后的页面——先对其执行 `web_extract`。
- **过度引用。** 每句最多三个 id；每个从句都加引用会让文本难以阅读，也会掩盖
  究竟由哪个来源支撑核心论断。
- **在代码/配置产物中引用台账。** 来源说明应放在正文交付物和文档页眉中，而不是
  生成的代码内部。
- **并行子代理。** 每个子代理都有自己的工作目录；如果最终要合并它们的输出，
  请使用 `--ledger`（或 `HERMES_CITATION_LEDGER`）让它们共同指向一份台账，
  否则各自的 id 会发生冲突。
- **引用搜索摘要而非页面。** 证据引文必须来自提取后的页面文本，而不是搜索结果
  描述——先执行 `web_extract`，保存文本，再对该文件执行 `quote --from`。
- **在 `quote --text` 中使用转述。** 逐字检查会拒绝它；正确做法是找到实际句子，
  而不是不断改写，直到碰巧匹配。
- **把 `[unverified]` 当作逃避手段。** 它用于标记极少数确实无法找到来源的论断；
  如果大多数句子都有该标记，说明任务需要更多检索，而不是更多标记。
- **手工编辑 Sources 区块。** 使用 `render --replace-in <draft>`；自行切割文件可能
  产生过期或重复的区块，随后会被 `verify` 标记。

## 验证

```bash
python3 "$S" verify report.md --strict --min-coverage 0.5
```

绿色通过意味着：草稿中的每个 `[n]` 都存在于台账中，Sources 区块严格列出了所有
被引用的 id 及台账中的 URL，而且带来源属性的句子中，已引用比例达到阈值。即使
退出码为 0，也要阅读警告——已登记却未被引用的来源，通常意味着某项论断在编辑
过程中丢失了出处标注。
