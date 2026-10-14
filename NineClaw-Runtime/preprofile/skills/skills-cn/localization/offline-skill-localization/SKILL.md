---
name: offline-skill-localization
description: Use when localizing Skill libraries for offline delivery.
---

# Offline Skill Localization

将英文 Skill 库制作成适合离线交付的高质量中文镜像，同时保持 Agent 的执行语义、包结构和可回退性。

## 核心标准

同时服务两类读者：

- **人需要理解逻辑：**自然翻译用途、触发条件、工作流、判断、约束、警告、输入输出和失败解释。
- **AI 需要精确执行：**保留 Skill/目录/文件名、YAML keys、commands、flags、paths、environment variables、APIs、config keys、schemas、identifiers、tool/library/model names、regex、formulas、LaTeX、URLs、Markdown targets 和精确 prompts/templates。

不追求中文覆盖率。验收标准是“人能放心看懂逻辑，AI 能保持准确执行”。命令密集或纯 Agent-facing 内容可直接保留英文。

## 不可违背的边界

1. 将英文源目录视为只读基准；只写独立目标镜像。
2. 保持完整文件路径集合、Skill 数量、包名、目录名和文件名一致。
3. `SKILL.md` 的 `name` 保持英文；frontmatter 除 `description` 外默认逐字保持。
4. fenced code blocks 连同 comments/docstrings 逐字节保持。
5. inline code spans 按原顺序逐字保持。
6. 非 Markdown 附件逐字节保持。
7. 需要恢复 Agent-facing 内容时，直接从英文源提取并复制；禁止凭记忆手写或“翻译回英文”。
8. 不执行示例代码来验证翻译；使用静态结构比对。
9. 不依赖公网翻译服务；离线环境中由当前模型完成本地文本转换。

## 工作流

### 1. 建立基线与镜像

- 枚举全部 `SKILL.md`、Markdown 和附件；忽略 `.DS_Store`、`Thumbs.db`、`desktop.ini` 与 `__MACOSX` 等操作系统元数据。
- 记录 Skill 数、文件数和确定性源树摘要。
- 完整复制源目录到独立目标，如 `skills-cn`。
- 验证初始路径集合和附件哈希一致。

### 2. 划分内容

**翻译：**
- purpose、trigger、workflow、decision、constraint、warning；
- 标题、普通表格、清单、解释、错误含义和链接标签；
- frontmatter `description`，但保留重要英文触发词。

**直接保留英文源：**
- fenced code、inline code、terminal commands、flags、paths；
- YAML/JSON/schema keys、APIs、identifiers、URLs、formulas、LaTeX；
- 精确执行 prompts/templates 和命令密集章节；
- 英文更准确或对触发有价值的技术词。

技术术语按语境决定；首次出现可使用“中文解释（English term）”。

### 3. 分片执行

- 按互不重叠的 Skill 包或文件组划分 worker。
- 每个任务明确只读源、精确目标文件和禁止越界写入。
- 大型包按少量文件分片，避免超时。
- 不让多个 worker 写同一文件。
- 进程超时、API 最终回传失败或 mutation verifier 警告都不等于产物失败；先检查真实文件，再决定重派。

### 4. 结构验收

运行：

```bash
python scripts/verify_localized_tree.py SOURCE DESTINATION
```

必须满足：

- 路径集合、Skill 数和 `name` 一致；
- frontmatter 仅允许 `description` 变化；
- fenced blocks、inline spans、URLs 和 Markdown targets 保持；
- 非 Markdown 文件哈希一致；
- UTF-8 有效；
- 每个 `SKILL.md` 的人类逻辑包含中文。

例外参数只能记录已人工解释的 parser boundary，不能掩盖未知错误：

```bash
--allow-fence-exception REL_PATH
--allow-inline-order-exception REL_PATH
--allow-inline-exception REL_PATH
```

典型合法例外：四反引号外层模板包含三反引号代码；TeX 使用双反引号表示引号。普通 inline code 或 fence 变化必须从英文源恢复。

### 5. 内部链接验收

运行：

```bash
python scripts/audit_internal_links.py DESTINATION
```

标题翻译会改变自动生成的 anchor。保留原链接 target，在对应中文标题前添加稳定英文锚点：

```html
<a id="original-english-slug"></a>
```

按源/目标标题的顺序与层级唯一映射；映射不唯一时停止并人工检查。

### 6. 双语语义审校

结构通过后，独立审校人类可读部分：

- 逻辑遗漏、条件反转、MUST/NEVER 弱化；
- 领域术语误译和不自然直译；
- proper names、transliterations、citation conventions；
- trigger vocabulary 是否被删除；
- 普通中文逻辑是否仍残留无价值英文。

不要把有意保留的 commands、prompts、templates 或双语对照章节误判为漏译。只修复具体问题；每轮修复后重新运行两个脚本。

### 7. 源完整性与交付

- 对比源树摘要或翻译开始后的 source mtime；不得出现源写入。
- 最终报告 Skill 数、文件数、翻译 Markdown 数、附件变化、UTF-8、结构错误、parser exceptions 和失效链接。
- 保留英文源作为回退副本，不删除。

## 恢复规则

- **代码或 inline literals 损坏：**整包从英文源恢复后重译，不修补大量不确定改动。
- **编辑器误报 binary：**先严格 UTF-8 decode，再检查 NUL/控制字符；有效文本不得因读取器采样误报而回滚。
- **正常 patch 拒绝有效 UTF-8：**使用确定性 exact replacement，要求旧字符串恰好出现一次，写后立即完整复验。
- **子 Agent 声称成功但无写入：**以目标文件内容为准。
- **最终 API 回传失败但文件已正确写入：**不要重跑有效工作。
- **机器翻译结构通过但术语差：**做双语语义审校，不将结构通过等同于质量通过。

## 完成条件

只有以下条件全部满足才交付：

- 全部 Skill 和文件完整对应；
- 人类逻辑自然、完整、可信；
- Agent-facing 内容来自英文源且执行语义不变；
- 两个验证脚本通过，或仅剩逐项解释并记录的 parser warnings；
- 内部链接为零失效；
- 英文源未修改，目标镜像可独立交付和回退。
