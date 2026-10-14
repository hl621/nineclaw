# *ACL 论文样式

本目录包含 *ACL 会议的最新 LaTeX 模板。

## 作者须知

向 *ACL 会议提交的论文必须使用 ACL 官方样式模板。

LaTeX 样式文件可通过以下方式获取：

- 使用 [Overleaf 模板](https://www.overleaf.com/latex/templates/association-for-computational-linguistics-acl-conference/jvxskxpnznfj)
- 从本仓库获取
- 下载 [.zip 文件](https://github.com/acl-org/acl-style-files/archive/refs/heads/master.zip)

有关示例，请参阅 [`acl_latex.tex`](https://github.com/acl-org/acl-style-files/blob/master/acl_latex.tex)。

请遵循适用于所有 *ACL 会议的论文格式指南：

- [论文格式指南](https://acl-org.github.io/ACLPUB/formatting.html)

作者不得修改这些样式文件，也不得使用为其他会议设计的模板。

## 出版主席须知

如需针对您的会议调整样式文件，请 fork 本仓库并进行必要的修改。您至少需要更新会议名称并重命名文件。

如果您对模板所做的改进也应沿用到今后的会议，请提交 pull request。提前感谢！

在旧版模板中，作者需要填写 START submission ID，以便将其印在匿名版本每一页的顶部。现在已不再需要这样做，因为 START 已支持自动添加该标记。目前的操作方式是由程序委员会主席向 support@softconf.com 发送电子邮件提出请求。

## 修改样式文件的说明

- 在 GitHub 中 merge pull request，或 push 到 GitHub
- 从 GitHub git pull 到本地仓库
- 然后，从本地仓库 git push 到 Overleaf 项目
    - Overleaf 项目地址为 https://www.overleaf.com/project/5f64f1fb97c4c50001b60549
    - Overleaf git URL 为 https://git.overleaf.com/5f64f1fb97c4c50001b60549
- 然后，在 Overleaf 中依次点击 "Submit" 和 "Submit as Template"，请求 Overleaf 使用该项目更新 Overleaf 模板
