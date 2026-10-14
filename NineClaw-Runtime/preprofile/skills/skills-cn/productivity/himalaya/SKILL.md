---
name: himalaya
description: "Himalaya CLI：通过终端使用 IMAP/SMTP 收发电子邮件。"
version: 1.1.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Email, IMAP, SMTP, CLI, Communication]
    homepage: https://github.com/pimalaya/himalaya
prerequisites:
  commands: [himalaya]
---

# Himalaya 电子邮件 CLI

Himalaya 是一款 CLI 电子邮件客户端，可通过 IMAP、SMTP、Notmuch 或 Sendmail 后端在终端中管理邮件。

本技能独立于 Hermes Email 网关适配器。网关
适配器让用户可以向代理发送电子邮件，并使用 Hermes 内置的 IMAP/SMTP
适配器；本技能则让代理通过终端工具操作邮箱，并且
需要外部 `himalaya` CLI。

## 参考资料

- `references/configuration.md`（配置文件设置 + IMAP/SMTP 身份验证）
- `references/message-composition.md`（用于编写邮件的 MML 语法）

## 前置条件

1. 已安装 Himalaya CLI（运行 `himalaya --version` 验证）
2. 配置文件位于 `~/.config/himalaya/config.toml`
3. 已配置 IMAP/SMTP 凭据（密码已安全存储）

### 安装

```bash
# Pre-built binary (Linux/macOS — recommended)
curl -sSL https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh | PREFIX=~/.local sh

# macOS via Homebrew
brew install himalaya

# Or via cargo (any platform with Rust)
cargo install himalaya --locked
```

## 配置设置

运行交互式向导来设置账户：

```bash
himalaya account configure
```

或者手动创建 `~/.config/himalaya/config.toml`：

```toml
[accounts.personal]
email = "you@example.com"
display-name = "Your Name"
default = true

backend.type = "imap"
backend.host = "imap.example.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@example.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show email/imap"  # or use keyring

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show email/smtp"

# Folder aliases (himalaya v1.2.0+ syntax). Required whenever the
# server's folder names don't match himalaya's canonical names
# (inbox/sent/drafts/trash). Gmail is the common case — see
# `references/configuration.md` for the `[Gmail]/Sent Mail` mapping.
folder.aliases.inbox = "INBOX"
folder.aliases.sent = "Sent"
folder.aliases.drafts = "Drafts"
folder.aliases.trash = "Trash"
```

> **请特别注意别名语法。** v1.2.0 之前的文档使用
> `[accounts.NAME.folder.alias]` 子节（单数形式 `alias`）。
> v1.2.0 会静默忽略这种形式——TOML 可以正常解析，但
> 别名解析器从不读取它，因此每次查找都会回退到
> 规范名称。在 Gmail 上，这意味着 SMTP 投递成功*之后*，
> 保存到“已发送”会失败，且 `himalaya message send` 以非零状态退出。
> 任何因该退出代码而重试的调用方（代理、脚本或用户）
> 都会重新执行整个发送流程（包括 SMTP），从而向收件人
> 发送重复邮件。始终使用 `folder.aliases.X`（复数形式、点分
> 键，直接置于 `[accounts.NAME]` 下）。

## Hermes 集成说明

- **读取、列出、搜索、移动、删除**均可直接通过终端工具完成
- **编写/回复/转发**——为确保可靠性，建议使用管道输入（`cat << EOF | himalaya template send`）。交互式 `$EDITOR` 模式可配合 `pty=true` + 后台模式 + process 工具使用，但需要知道编辑器及其命令
- 使用 `--output json` 获取更便于程序解析的结构化输出
- `himalaya account configure` 向导需要交互式输入——请使用 PTY 模式：`terminal(command="himalaya account configure", pty=true)`

## 常用操作

### 列出文件夹

```bash
himalaya folder list
```

### 列出邮件

列出 INBOX 中的邮件（默认）：

```bash
himalaya envelope list
```

列出指定文件夹中的邮件：

```bash
himalaya envelope list --folder "Sent"
```

分页列出：

```bash
himalaya envelope list --page 1 --page-size 20
```

### 搜索邮件

```bash
himalaya envelope list from john@example.com subject meeting
```

### 阅读邮件

按 ID 阅读邮件（显示纯文本）：

```bash
himalaya message read 42
```

导出原始 MIME：

```bash
himalaya message export 42 --full
```

### 回复邮件

要从 Hermes 以非交互方式回复，请先读取原始邮件，编写回复，然后通过管道传入：

```bash
# Get the reply template, edit it, and send
himalaya template reply 42 | sed 's/^$/\nYour reply text here\n/' | himalaya template send
```

或者手动构建回复：

```bash
cat << 'EOF' | himalaya template send
From: you@example.com
To: sender@example.com
Subject: Re: Original Subject
In-Reply-To: <original-message-id>

Your reply here.
EOF
```

全部回复（交互式——需要 $EDITOR，请改用上面的模板方式）：

```bash
himalaya message reply 42 --all
```

### 转发邮件

```bash
# Get forward template and pipe with modifications
himalaya template forward 42 | sed 's/^To:.*/To: newrecipient@example.com/' | himalaya template send
```

### 撰写新邮件

**非交互方式（从 Hermes 使用此方式）**——通过 stdin 传入邮件：

```bash
cat << 'EOF' | himalaya template send
From: you@example.com
To: recipient@example.com
Subject: Test Message

Hello from Himalaya!
EOF
```

或者使用邮件头参数：

```bash
himalaya message write -H "To:recipient@example.com" -H "Subject:Test" "Message body here"
```

注意：不通过管道提供输入时，`himalaya message write` 会打开 `$EDITOR`。这可配合 `pty=true` + 后台模式使用，但通过管道输入更简单、更可靠。

### 移动/复制邮件

将邮件移至文件夹（目标文件夹在前，邮件 ID 在后）：

```bash
himalaya message move "Archive" 42
```

将邮件复制到文件夹（目标文件夹在前，邮件 ID 在后）：

```bash
himalaya message copy "Important" 42
```

### 删除邮件

```bash
himalaya message delete 42
```

### 管理标记

添加标记：

```bash
himalaya flag add 42 --flag seen
```

移除标记：

```bash
himalaya flag remove 42 --flag seen
```

## 多个账户

列出账户：

```bash
himalaya account list
```

使用指定账户：

```bash
himalaya --account work envelope list
```

## 附件

保存邮件中的附件：

```bash
himalaya attachment download 42
```

保存到指定目录：

```bash
himalaya attachment download 42 --downloads-dir ~/Downloads
```

## 输出格式

大多数命令都支持使用 `--output` 获取结构化输出：

```bash
himalaya envelope list --output json
himalaya envelope list --output plain
```

## 调试

启用调试日志：

```bash
RUST_LOG=debug himalaya envelope list
```

启用完整跟踪和回溯：

```bash
RUST_LOG=trace RUST_BACKTRACE=1 himalaya envelope list
```

## 提示

- 使用 `himalaya --help` 或 `himalaya <command> --help` 查看详细用法。
- 邮件 ID 与当前文件夹相关；文件夹变更后请重新列出邮件。
- 编写带附件的富文本邮件时，请使用 MML 语法（参阅 `references/message-composition.md`）。
- 使用 `pass`、系统钥匙串或输出密码的命令安全存储密码。
