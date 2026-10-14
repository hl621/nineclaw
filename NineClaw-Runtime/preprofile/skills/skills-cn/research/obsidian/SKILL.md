---
name: obsidian
description: 读取、搜索、创建和编辑 Obsidian 仓库中的笔记。
platforms: [linux, macos, windows]
---

# Obsidian 仓库

此 Skill 用于以文件系统为先的 Obsidian 仓库操作：读取笔记、列出笔记、搜索笔记文件、创建笔记、追加内容以及添加 wikilink。

## 仓库路径

调用文件工具前，应先使用已知或已解析的仓库路径。

文档约定使用 `OBSIDIAN_VAULT_PATH` 环境变量作为仓库路径，例如从 `${HERMES_HOME:-~/.hermes}/.env` 读取。如果该变量未设置，则使用 `~/Documents/Obsidian Vault`。

文件工具不会展开 shell 变量。不要将含有 `$OBSIDIAN_VAULT_PATH` 的路径传给 `read_file`、`write_file`、`patch` 或 `search_files`；请先解析仓库路径，再传入具体的绝对路径。仓库路径可能包含空格，这也是优先使用文件工具而非 shell 命令的另一个原因。

如果仓库路径未知，可以使用 `terminal` 解析 `OBSIDIAN_VAULT_PATH`，或检查回退路径是否存在。路径确定后，应切回文件工具。

## 读取笔记

使用 `read_file` 和已解析的笔记绝对路径。优先使用此工具而非 `cat`，因为它会提供行号和分页。

## 列出笔记

使用 `search_files`，设置 `target: "files"`，并传入已解析的仓库路径。优先使用此工具而非 `find` 或 `ls`。

- 要列出所有 Markdown 笔记，请在仓库路径下使用 `pattern: "*.md"`。
- 要列出某个子文件夹，请在该子文件夹的绝对路径下搜索。

## 搜索

使用 `search_files` 搜索文件名和内容。优先使用此工具而非 `grep`、`find` 或 `ls`。

- 搜索文件名时，使用 `search_files`，设置 `target: "files"`，并将文件名模式作为 `pattern`。
- 搜索笔记内容时，使用 `search_files`，设置 `target: "content"`，将内容正则表达式作为 `pattern`；如果只想匹配 Markdown 笔记，则设置 `file_glob: "*.md"`。

## 创建笔记

使用 `write_file`，传入已解析的绝对路径和完整 Markdown 内容。优先使用此工具而非 shell heredoc 或 `echo`，因为它能避免 shell 引用问题并返回结构化结果。

## 向笔记追加内容

如果操作不会变得别扭，应优先采用原生文件工具工作流：

- 使用 `read_file` 读取目标笔记。
- 有稳定上下文时，使用 `patch` 进行锚定追加，例如在现有标题后添加一节，或在已知的末尾区块之前追加内容。
- 如果重写整篇笔记比构造脆弱的补丁更清晰，则使用 `write_file`。

使用 `patch` 进行锚定追加时，将锚点替换为“锚点加新增内容”。

如果只是简单追加且没有稳定上下文，在它是最清晰且安全的选项时，可以使用 `terminal`。

## 定向编辑

当当前内容提供了稳定上下文时，使用 `patch` 对笔记进行局部修改。优先使用此工具而非通过 shell 重写文本。

## Wikilink

Obsidian 使用 `[[Note Name]]` 语法链接笔记。创建笔记时，用这种语法链接相关内容。
