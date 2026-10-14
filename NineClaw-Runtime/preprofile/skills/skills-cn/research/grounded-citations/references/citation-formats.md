# 各类输出目标的引用格式

台账本身与格式无关：`sources.py render --style ...` 负责生成区块，本文档则说明
区块应放在哪里，以及内联标记应采用什么形式。

## Markdown / 聊天回答

紧跟在句子之后添加内联 `[n]`。在末尾放置区块：

```
## Sources

[1] https://example.com/a — Page title
[2] https://example.com/b
```

`--style plain` 会生成不带 Markdown 标题层级的 `Sources:` 标头，适合在聊天回复中
使用，因为此时 Markdown 标题反而会造成干扰。

## 通过 LaTeX 生成 PDF（`latex-pdf-report` 技能）

使用 `--style footnotes`，在每个 id 首次出现时将其映射到 `\footnote{}`；也可以
保留数字标记，并生成尾注章节。如果报告需要采用参考文献形式，`--style bibtex`
会生成 `@misc` 条目，并以 `source<N>` 为键；使用 `\cite{source3}` 引用，并让
BibTeX 渲染列表。

不要混用：要么使用数字 `[n]` + Sources 章节，要么使用 `\cite{}` + BibTeX。
在同一文档中使用两套编号系统，比完全不用编号还要糟糕。

## Word（.docx，`docx` 技能）

对于供人工编辑的正文文档，真正的脚注优于内联方括号——审阅者通常期望看到 Word
脚注。让脚注编号与台账 id 保持一致，这样 `verify` 仍可对作为权威原稿的 Markdown
执行验证，再由该 Markdown 生成 .docx。

## 幻灯片（.pptx，`powerpoint` 技能）

在项目符号文本中内联 `[n]`，并在末尾添加一页使用 `--style plain` 渲染的
“Sources”幻灯片。绝不要把 URL 放进正文项目符号——这会破坏版式，而且在投影播放的
演示文稿中无法点击。

## 电子表格（.xlsx）

添加一个保存 id 的 `source` 列，再创建一张 `Sources` 工作表，其内容由
`render --style plain` 生成。不要把 URL 粘贴进数据单元格。

## Wiki / 多页面输出（`llm-wiki`、Obsidian）

每页都设置 Sources 区块，各页通过同一份台账共享 id。由于 id 是台账中的身份标识，
`[7]` 在整个 Wiki 中始终表示同一个页面——这种一致性正是一次构建的不同页面之间
不应重置台账的原因。

## 研究论文

移交给 `research-paper-writing` 技能。使用 `--style bibtex` 导出到
`references.bib`，然后遵循该技能的引用验证流程（它会用 grep 将 `\cite{...}`
与 .bib 对照检查）。台账的职责到生成已验证的 URL 条目为止；出版场所规定的格式
属于该技能的职责范围。

## 代码和配置产物

不要在生成的代码内部添加引用。如果出处很重要，应将其写入提交信息、PR 正文或
文档页眉，而不是散落在源代码各处的注释中。

