# *ACL 论文集格式说明

以下说明适用于向 ACL 会议投稿以供评审的论文（下称“评审版”），以及被接收并将在会议论文集中发表的论文（下称“终稿版”）。
所有作者均须遵守这些规范。

## 样式文件

*ACL 提供符合这些要求的 LaTeX 和 Microsoft Word 样式文件，可在以下地址找到：

> https://acl-org.github.io/ACLPUB/

我们强烈建议使用这些样式文件，它们已针对 *ACL 论文集进行了适当定制。

## 论文篇幅

会议接受长论文和短论文投稿。
长论文评审版的正文最多为八（8）页，参考文献页数不限。
论文被接收后，长论文终稿版可额外增加一页——正文最多为九（9）页，致谢和参考文献页数不限——以便作者根据审稿意见进行修改。
短论文评审版的正文最多为四（4）页，参考文献页数不限。
短论文终稿版最多为五（5）页，致谢和参考文献页数不限。
无论长论文还是短论文，正文中的所有图和表均须计入上述页数限制。

会议鼓励提交附录和补充材料，它们不受上述页数限制。但是，论文评审版必须自成一体：审稿人可自行决定是否查看附录或补充材料。更多信息请参见[附录](#Appendices)和[补充材料](#Supplementary Material)。

评审版不应要求读者参阅审稿人无法获取的文档、代码或数据资源来了解更多细节。

不符合这些要求的论文可能不经评审即被拒稿。

研讨会主席可能对允许的篇幅以及是否接受附录或补充材料另有规定。
一如既往，相应的征稿启事是权威依据。

## 匿名要求

由于采用双盲评审，评审版不得包含任何可识别作者身份的信息（如姓名、所属机构或 URL）。
必须避免会暴露作者身份的自引表述，例如：

> We previously showed (Gusfield, 1997)...

同时也应避免匿名引用，例如：

> We previously showed (Anonymous, 1997)...

应改用如下引用方式：

> Gusfield (1997) previously showed...

评审版不得包含致谢。

**不符合这些要求的论文可能不经评审即被拒稿。**

所投稿论文的任何非存档初步版本均应在投稿表单中列明，但不得在论文评审版中列出。
审稿人通常知道作者可能曾在其他场合展示其工作的初步版本，但不会获得投稿表单中列出的既往展示记录。

论文被会议接收后，终稿版应包含作者姓名和所属机构，并可使用自引表述。

## 一稿多投

已经或将要提交至其他会议或出版物的论文，必须在投稿时于 START 投稿表单中注明；若被 *ACL 接收，则必须撤回向其他会议或出版物提交的稿件。
被 *ACL 接收并安排报告的论文，其作者必须在终稿提交截止日期（“camera-ready deadline”）前告知程序主席论文是否会进行报告。
对于在内容或结果上与将要（或已经）在其他地方发表的论文存在显著重叠的论文，我们不接受其发表或报告。

向 *ACL 提交多篇论文的作者必须确保各篇投稿在内容或结果上不存在显著重叠（>25%）。

## 格式说明

### 文件格式

论文必须采用 Adobe Portable Document Format (PDF)。
请确保 PDF 文件嵌入所有必要字体（尤其是树形图、符号和亚洲语言所用字体）。
打印或创建 PDF 文件时，打印机设置中通常会提供不嵌入字体、嵌入所有字体或仅嵌入非标准字体的选项。
请务必选择嵌入*所有*字体的选项。
**提交前，请在不同于创建该 PDF 的计算机上打印，以测试该文件。**

某些文字处理软件可能会生成非常大的 PDF 文件，其中每一页都被渲染为图像。
此类图像的再现质量可能较差。
遇到这种情况时，请尝试通过其他方式生成 PDF。

所有论文必须使用 **A4 纸张格式**（21 cm x 29.7 cm）。
不得使用任何其他纸张尺寸投稿。

如果无法满足上述要求，请尽快联系出版主席。

### 版面布局

除页码外，所有文本都必须位于页边距以内。

评审版应在下方页边距中央标注页码，但**终稿版不得标注页码。**

稿件必须采用双栏排版。
双栏格式的例外包括标题、作者姓名和完整地址（这些内容必须在第一页顶部居中），以及任何通栏图或表。

A4 纸页面的精确尺寸如下：

* 左边距：2.5 cm
* 右边距：2.5 cm
* 上边距：2.5 cm
* 下边距：2.5 cm
* 栏宽：7.7 cm
* 栏高：24.7 cm
* 栏间距：0.6 cm

评审版应打印行号标尺（即文章左右页边距中的行号），以便审稿人评论论文中的特定行。
行号标尺不应改变页面上任何其他内容的外观。
终稿版不得包含行号标尺。

### 字体

所有文本（非拉丁文字和数学公式除外）均应使用 **Times Roman**。
如果无法使用 Times Roman，可以使用 **Times New Roman** 或 **Computer Modern Roman.**

下表规定了稿件中各类文本必须使用的字号和字形。

| 文本类型              | 字号      | 字形  |
| --------------------- | --------- | ----- |
| 论文标题              | 15 pt     | 粗体  |
| 作者姓名              | 12 pt     | 粗体  |
| 作者所属机构          | 12 pt     |       |
| 单词 ``Abstract''     | 12 pt     | 粗体  |
| 节标题                | 12 pt     | 粗体  |
| 小节标题              | 11 pt     | 粗体  |
| 正文                  | 11 pt     |       |
| 图表标题              | 10 pt     |       |
| 摘要正文              | 10 pt     |       |
| 参考文献              | 10 pt     |       |
| 脚注                  | 9 pt      |       |

### 标题和作者

标题、作者姓名和所属机构应横跨双栏居中排版。

标题应置于第一页顶部中央，使用 15 磅粗体。
较长的标题应分为两行排版，两行之间不得留空行。
标题应位于距页面顶部 2.5 cm 处。
标题应采用[标题式大小写](https://apastyle.apa.org/style-grammar-guidelines/capitalization/title-case)；不要将标题全部写成大写字母，但通常应全大写或首字母大写的缩略词（如“BLEU”）或专有名词（如“English”）除外。

作者姓名和所属机构应置于标题下方。
请写出作者全名；除非通常本就以首字母形式书写，否则不要将名字缩写为首字母（应写“Margaret Mitchell”，而非“M. Mitchell”）。
姓氏不得全部使用大写字母（应写“Mitchell”，而非“MITCHELL”）。

不要使用脚注标注所属机构。
所属机构信息应包含作者的完整地址，并尽可能包含电子邮件地址。

标题、作者姓名和地址应与论文投稿网站中填写的信息完全一致，以确保会议所有出版物中的作者信息一致。
如有差异，出版主席可能会在不征询您的情况下予以处理；因此，为维护您自身的利益，请仔细核对这些信息是否一致。

第一页正文应从距页面顶部 7.5 cm 处开始。
**即使是论文评审版，也应为姓名和地址预留足够空间，以便终稿版能够容纳这些信息。**

### 摘要

摘要应置于第一栏开头。
在摘要正文上方，将 **Abstract** 一词居中排版，使用 12 磅粗体。
摘要宽度应在正常栏宽的基础上
左右各缩窄 0.6 cm。
摘要正文应使用 10 磅 Roman 字体，单倍行距。

摘要应简明概括论文的总体论点和结论。
不得超过 200 个单词。

### 正文

紧接摘要之后开始排版正文，并继续采用双栏格式。
正文应使用 11 磅 Roman 字体，单倍行距。

新段落首行缩进 0.4 cm，但每节的第一段除外。

### 章节

使用阿拉伯数字对各节编号，以便交叉引用。
小节编号由节号和小节号组成，两者以点号分隔，均使用阿拉伯数字，例如：

> 1 Introduction

或

> 6.1 File Format

### 脚注
脚注应置于页面底部，并使用 9 磅字体。
脚注可以编号，也可以使用星号或其他符号指代。
脚注与正文之间应以横线分隔。

### 图和表

图和表应尽可能放在论文中首次讨论它们的位置附近，而不是统一置于文末。
较宽的图/表可以横跨双栏。

为照顾色觉障碍人士（以及使用黑白打印机的读者），强烈建议确保图表在灰度下仍然清晰可读。
并非禁止使用颜色，但作者应确保表格和图形不只依赖颜色来传达关键差异。

**图表标题：**
每幅图/每个表都应提供标题，并按如下格式依次编号：

> Figure 1: Caption of the Figure.

以及

> Table 1: Caption of the Table.

图表标题应置于图/表下方，使用 10 磅 Roman 字体。
单行标题应居中。
超过一行的标题应左对齐。

### 超链接

文档内部和外部超链接应使用深蓝色（十六进制 #000099），且不得加下划线或边框。

### 非英语文本

英语以外的语言文本应附有英语译文；使用非拉丁文字书写的文本还应\emph{also}附有拉丁字母转写，因为并非所有读者都能轻松辨认非拉丁字符。

例如，παράδειγμα *paradeigma* ‘example’ 是一个希腊语单词，以下是一个希腊语句子：

> Αυτό είναι ένα παράδειγμα.  
> auto einai ena paradeigma.  
> ‘This is an example.’

### 引用

正文中的引用可以置于括号内（Gusfield, 1997）；如果作者姓名本身出现在正文中，则写作：Gusfield (1997)。
存在歧义时，应在年份后附加小写字母。
引用两位作者的论文时应写出两位作者的姓名（Aho and Ullman, 1972）；引用两位以上作者的论文时，则应使用第一作者的姓名和 ``et al.''（Chandra et al., 1981）。
多个引用应合并在同一对括号内（Gusfield, 1997; Aho and Ullman, 1972）。

避免将完整的括号式引用用作句子成分。
不要写成：

> (Gusfield, 1997) showed that ...  
> In (Gusfield, 1997), ...''

应写成：

> Gusfield (1997) showed that ...  
> In Gusfield (1997), ...

投稿应准确引用既往及相关工作，包括代码和数据。
如果某项既往工作有多个发表版本，应引用其中经过同行评审并正式归档出版的版本。
如果某项既往工作有多个版本，应引用作者实际使用的版本。

### 致谢

致谢应紧接在参考文献之前。
致谢部分不要编号。
评审版中不得包含此部分。

### 参考文献

将完整的参考文献集中列在不编号的 **References** 节标题下。
References 部分应置于所有附录之前。
参考文献应按第一作者姓名的字母顺序排列，而不是按其在正文中的出现顺序排列。

应采用一致的格式提供尽可能完整的引文信息，例如 [Computational Linguistics 的格式](http://cljournal.org/style_guide_refs.html)或 [Publication Manual of the American Psychological Association](https://apastyle.apa.org/products/publication-manual-7th-edition) 中的格式。
作者姓名应使用全名，而不只是首字母缩写。
作者不应依赖自动引文索引来提供准确的既往及相关工作参考文献信息。

作为推动 ACL 材料在本学科之外得到更广泛使用和引用的工作之一，ACL 已注册成为 CrossRef 会员及数字对象标识符（DOI）注册机构；DOI 是注册永久 URN 以引用学术材料的标准。

所有参考文献均须尽可能包含所有被引作品的 DOI；若无 DOI，则次选为 ACL Anthology 页面链接。
当前的 [ACL Anthology](https://aclweb.org/anthology/) 应当收录了大多数材料的相应记录。

期刊论文示例：

> Rie Kubota Ando and Tong Zhang. 2005. [A framework for learning predictive structures from multiple tasks and unlabeled data](https://www.jmlr.org/papers/v6/ando05a.html). *Journal of Machine Learning Research*, 6:1817–1853.

带 DOI 的非 ACL 会议论文集论文示例：

> Galen Andrew and Jianfeng Gao. 2007. [Scalable training of L1-regularized log-linear models](https://doi.org/10.1145/1273496.1273501). In *Proceedings of the 24th International Conference on Machine Learning*, pages 33–40.

带 DOI 的 ACL Anthology 论文示例：

> James Goodman, Andreas Vlachos, and Jason Naradowsky. 2016. [Noise reduction and targeted exploration in imitation learning for Abstract Meaning Representation parsing](http://dx.doi.org/10.18653/v1/P16-1001). In *Proceedings of the 54th Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)*, pages 1–45711, Berlin, Germany. Association for Computational Linguistics.

不带 DOI 的 ACL Anthology 论文示例：

> Benjamin Börschinger and Mark Johnson. 2011. [A particle filter algorithm for Bayesian word segmentation](https://www.aclweb.org/anthology/U11-1004/). In *Proceedings of the Australasian Language Technology Association Workshop 2011*, pages 10–44718, Canberra, Australia.

arXiv 论文示例：

> Mohammad Sadegh Rasooli and Joel R. Tetreault. 2015. [Yara parser: A fast and accurate dependency parser](http://arxiv.org/abs/1503.06733). *Computing Research Repository*, arXiv:1503.06733. Version 2.

<a id="Appendices"></a>

## 附录

附录是供读者阅读的材料，可包括对阅读和理解论文并非关键的引理、公式、证明和表格。
附录应按字母顺序编号，并提供信息明确的标题：

> Appendix A. Title of Appendix

附录应置于参考文献之后。

附录的评审版必须遵循与论文正文相同的匿名要求。

<a id="Supplementary Material"></a>

## 补充材料

投稿可以包含研究中使用并在论文中描述的非阅读型补充材料。
任何随附的软件和/或数据均应酌情包含许可证及研究审查相关文档。
补充材料可以说明预处理决策、模型参数，以及复现论文所报告实验所需的其他细节。
看似微小的预处理决策有时也会对性能产生巨大影响，因此，记录这些决策对于准确刻画当前最先进的方法至关重要。

尽管如此，补充材料应当是论文的补充，而非论文的核心。
**滥用补充材料的投稿可能不经评审即被拒稿。**
补充材料可以包括正文无法容纳的证明或推导的解释或细节、特征或特征模板列表、系统输入和输出示例、伪代码或源代码，以及数据。
（源代码和数据应作为单独文件上传，而不应作为论文的一部分。）

论文不应依赖补充材料：尽管论文可以提及和引用补充材料，且审稿人可以获取补充材料，但不会要求他们评审补充材料。

补充材料的评审版必须遵循与论文正文相同的匿名要求。

## 致谢来源

本文件改编自早期 ACL 和 NAACL 论文集的格式说明，包括：
Steven Bethard、Ryan Cotterell 和 Rui Yan 编写的 ACL 2020 格式说明，
Douwe Kiela 和 Ivan Ivan Vulić 编写的 ACL 2019 格式说明，
Stephanie Lukin 和 Alla Roskovskaya 编写的 NAACL 2019 格式说明，
Shay Cohen、Kevin Gimpel 和 Wei Lu 编写的 ACL 2018 格式说明，
Margaret Mitchell 和 Stephanie Lukin 编写的 NAACL 2018 格式说明，
Jason Eisner 为 (NA)ACL 2017/2018 提供的 BibTeX 建议，
Dan Gildea 和 Min-Yen Kan 编写的 ACL 2017 格式说明，
Margaret Mitchell 编写的 NAACL 2017 格式说明，
Maggie Li 和 Michael White 编写的 ACL 2012 格式说明，
Jing-Shin Chang 和 Philipp Koehn 编写的 ACL 2010 格式说明，
Johanna D. Moore、Simone Teufel、James Allan 和 Sadaoki Furui 编写的 ACL 2008 格式说明，
Hwee Tou Ng 和 Kemal Oflazer 编写的 ACL 2005 格式说明，
Eugene Charniak 和 Dekang Lin 编写的 ACL 2002 格式说明，
以及由多人编写的更早期 ACL 和 EACL 格式，其中包括
John Chen、Henry S. Thompson 和 Donald Walker。
此外还采用了 *International Joint Conference on Artificial Intelligence* 和 *Conference on Computer Vision and Pattern Recognition* 格式说明中的部分内容。
