# Himalaya 配置参考

配置文件位置：`~/.config/himalaya/config.toml`

## 最小化 IMAP + SMTP 设置

```toml
[accounts.default]
email = "user@example.com"
display-name = "Your Name"
default = true

# IMAP backend for reading emails
backend.type = "imap"
backend.host = "imap.example.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "user@example.com"
backend.auth.type = "password"
backend.auth.raw = "your-password"

# SMTP backend for sending emails
message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "user@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.raw = "your-password"

# Folder aliases — required whenever server folder names differ
# from himalaya's canonical names. See "Folder Aliases" below.
folder.aliases.inbox = "INBOX"
folder.aliases.sent = "Sent"
folder.aliases.drafts = "Drafts"
folder.aliases.trash = "Trash"
```

## 密码选项

### 明文密码（仅用于测试，不推荐）

```toml
backend.auth.raw = "your-password"
```

### 从命令获取密码（推荐）

```toml
backend.auth.cmd = "pass show email/imap"
# backend.auth.cmd = "security find-generic-password -a user@example.com -s imap -w"
```

### 系统钥匙串（需要 keyring 功能）

```toml
backend.auth.keyring = "imap-example"
```

然后运行 `himalaya account configure <account>` 以存储密码。

## Gmail 配置

```toml
[accounts.gmail]
email = "you@gmail.com"
display-name = "Your Name"
default = true

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@gmail.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show google/app-password"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.gmail.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@gmail.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show google/app-password"

# Gmail folder mapping. Without these, save-to-Sent fails after
# SMTP delivery succeeds (Gmail's Sent folder is `[Gmail]/Sent Mail`,
# not `Sent`), and `himalaya message send` exits non-zero. Any
# caller that retries on that error will re-run SMTP — duplicate
# emails to recipients. Always include this block for Gmail.
folder.aliases.inbox = "INBOX"
folder.aliases.sent = "[Gmail]/Sent Mail"
folder.aliases.drafts = "[Gmail]/Drafts"
folder.aliases.trash = "[Gmail]/Trash"
```

**注意：** 如果启用了双重验证，Gmail 要求使用应用专用密码。

## iCloud 配置

```toml
[accounts.icloud]
email = "you@icloud.com"
display-name = "Your Name"

backend.type = "imap"
backend.host = "imap.mail.me.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@icloud.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show icloud/app-password"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.mail.me.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@icloud.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show icloud/app-password"
```

**注意：** 请在 appleid.apple.com 生成应用专用密码

## 文件夹别名

将 himalaya 的规范文件夹名称（`inbox`、`sent`、`drafts`、
`trash`）映射到服务器实际使用的名称。请使用
v1.2.0 的 `folder.aliases.X` 语法（复数形式、点分键，直接置于
`[accounts.NAME]` 下）：

```toml
[accounts.default]
# ... other account config ...

folder.aliases.inbox = "INBOX"
folder.aliases.sent = "Sent"
folder.aliases.drafts = "Drafts"
folder.aliases.trash = "Trash"
```

v1.2.0 也支持等效的 TOML 子节形式：

```toml
[accounts.default.folder.aliases]
inbox = "INBOX"
sent = "Sent"
drafts = "Drafts"
trash = "Trash"
```

> **不要使用单数形式 `alias`。** v1.2.0 之前的文档使用
> `[accounts.NAME.folder.alias]`（单数形式）。v1.2.0 会静默
> 忽略该子节——TOML 解析不会报错，但别名解析器从不读取它。
> 于是每次查找都会回退到规范名称。在 Gmail 中（实际的 `sent`
> 是 `[Gmail]/Sent Mail`），这意味着 SMTP 投递成功*之后*，保存到“已发送”会失败，
> 且 `himalaya message send` 以非零状态退出。
> 任何因该错误代码而重试的调用方（代理、脚本或用户）
> 都会重新执行整个发送流程（包括 SMTP），导致向收件人
> 发送重复邮件。始终使用 `folder.aliases.X`（复数形式）。

## 多个账户

```toml
[accounts.personal]
email = "personal@example.com"
default = true
# ... backend config ...

[accounts.work]
email = "work@company.com"
# ... backend config ...
```

使用 `--account` 切换账户：

```bash
himalaya --account work envelope list
```

## Notmuch 后端（本地邮件）

```toml
[accounts.local]
email = "user@example.com"

backend.type = "notmuch"
backend.db-path = "~/.mail/.notmuch"
```

## OAuth2 身份验证（适用于支持它的提供商）

```toml
backend.auth.type = "oauth2"
backend.auth.client-id = "your-client-id"
backend.auth.client-secret.cmd = "pass show oauth/client-secret"
backend.auth.access-token.cmd = "pass show oauth/access-token"
backend.auth.refresh-token.cmd = "pass show oauth/refresh-token"
backend.auth.auth-url = "https://provider.com/oauth/authorize"
backend.auth.token-url = "https://provider.com/oauth/token"
```

## 其他选项

### 签名

```toml
[accounts.default]
signature = "Best regards,\nYour Name"
signature-delim = "-- \n"
```

### 下载目录

```toml
[accounts.default]
downloads-dir = "~/Downloads/himalaya"
```

### 编写邮件时使用的编辑器

通过环境变量设置：

```bash
export EDITOR="vim"
```
