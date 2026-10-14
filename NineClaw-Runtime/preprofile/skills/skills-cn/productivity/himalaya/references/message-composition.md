# 使用 MML（MIME 元语言）编写邮件

Himalaya 使用 MML 编写邮件。MML 是一种基于 XML 的简单语法，可编译为 MIME 邮件。

## 基本邮件结构

一封电子邮件由一组**邮件头**和随后的**正文**组成，两者之间以一个空行分隔：

```
From: sender@example.com
To: recipient@example.com
Subject: Hello World

This is the message body.
```

## 邮件头

常用邮件头：

- `From`：发件人地址
- `To`：主要收件人
- `Cc`：抄送收件人
- `Bcc`：密送收件人
- `Subject`：邮件主题
- `Reply-To`：回复地址（若与 From 不同）
- `In-Reply-To`：所回复邮件的邮件 ID

### 地址格式

```
To: user@example.com
To: John Doe <john@example.com>
To: "John Doe" <john@example.com>
To: user1@example.com, user2@example.com, "Jane" <jane@example.com>
```

## 纯文本正文

简单的纯文本邮件：

```
From: alice@localhost
To: bob@localhost
Subject: Plain Text Example

Hello, this is a plain text email.
No special formatting needed.

Best,
Alice
```

## 使用 MML 编写富文本邮件

### 多部分邮件

可选的纯文本/HTML 部分：

```
From: alice@localhost
To: bob@localhost
Subject: Multipart Example

<#multipart type=alternative>
This is the plain text version.
<#part type=text/html>
<html><body><h1>This is the HTML version</h1></body></html>
<#/multipart>
```

### 附件

附加文件：

```
From: alice@localhost
To: bob@localhost
Subject: With Attachment

Here is the document you requested.

<#part filename=/path/to/document.pdf><#/part>
```

为附件指定自定义名称：

```
<#part filename=/path/to/file.pdf name=report.pdf><#/part>
```

多个附件：

```
<#part filename=/path/to/doc1.pdf><#/part>
<#part filename=/path/to/doc2.pdf><#/part>
```

### 内嵌图像

在正文中嵌入图像：

```
From: alice@localhost
To: bob@localhost
Subject: Inline Image

<#multipart type=related>
<#part type=text/html>
<html><body>
<p>Check out this image:</p>
<img src="cid:image1">
</body></html>
<#part disposition=inline id=image1 filename=/path/to/image.png><#/part>
<#/multipart>
```

### 混合内容（文本 + 附件）

```
From: alice@localhost
To: bob@localhost
Subject: Mixed Content

<#multipart type=mixed>
<#part type=text/plain>
Please find the attached files.

Best,
Alice
<#part filename=/path/to/file1.pdf><#/part>
<#part filename=/path/to/file2.zip><#/part>
<#/multipart>
```

## MML 标签参考

### `<#multipart>`

将多个部分组合在一起。

- `type=alternative`：同一内容的不同表现形式
- `type=mixed`：相互独立的部分（文本 + 附件）
- `type=related`：相互引用的部分（HTML + 图像）

### `<#part>`

定义邮件的一个部分。

- `type=<mime-type>`：内容类型（例如 `text/html`、`application/pdf`）
- `filename=<path>`：要附加的文件
- `name=<name>`：附件的显示名称
- `disposition=inline`：以内嵌方式显示，而非作为附件
- `id=<cid>`：供 HTML 引用的内容 ID

## 通过 CLI 编写邮件

### 交互式编写

打开您的 `$EDITOR`：

```bash
himalaya message write
```

### 回复（在编辑器中打开并附带引用的邮件）

```bash
himalaya message reply 42
himalaya message reply 42 --all  # reply-all
```

### 转发

```bash
himalaya message forward 42
```

### 从标准输入发送

```bash
cat message.txt | himalaya template send
```

### 通过 CLI 预填邮件头

```bash
himalaya message write \
  -H "To:recipient@example.com" \
  -H "Subject:Quick Message" \
  "Message body here"
```

## 提示

- 编辑器打开时会显示一个模板；请填写邮件头和正文。
- 保存并退出编辑器即可发送；不保存直接退出则取消发送。
- 发送时，MML 各部分会被编译为正确的 MIME 格式。
- 使用 `himalaya message export --full` 检查已接收邮件的原始 MIME 结构。
