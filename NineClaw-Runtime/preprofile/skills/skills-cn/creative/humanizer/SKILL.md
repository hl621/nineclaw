---
name: humanizer
description: "让文本更有人味：去除 AI 腔，写出真实文风。"
version: 2.5.1
author: Siqi Chen (@blader, https://github.com/blader/humanizer), ported by Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [writing, editing, humanize, anti-ai-slop, voice, prose, text]
    category: creative
    homepage: https://github.com/blader/humanizer
    related_skills: [songwriting-and-ai-music]
---

# Humanizer：去除 AI 写作模式

识别并去除 AI 生成文本的痕迹，让文字听起来自然、像人写的。本 Skill 基于 Wikipedia 的“Signs of AI writing”指南（由 WikiProject AI Cleanup 维护），其中的规律来自对数千个 AI 生成文本实例的观察。

**关键洞察：** LLM 使用统计算法猜测接下来应该出现什么。结果往往趋向统计上最可能的补全，因此会形成下文列出的种种典型模式。

## 何时使用此 Skill

用户提出以下要求时，请加载此 Skill：
- 对一段文字进行 "humanize"、"de-AI"、"de-slop" 或 "un-ChatGPT"
- 重写某些内容，让它听起来不像 LLM 所写
- 编辑草稿（博客文章、论文、PR 描述、文档、备忘录、电子邮件、推文、简历要点），使其更自然
- 在写作时模仿用户的文风
- 发布前检查文本中是否有 AI 痕迹

在撰写面向用户的文字（如发行说明、PR 描述、文档和摘要）时，也应将此 Skill 应用于**你自己的**输出。Hermes 的基础文风已经去掉了大多数这类模式，但专门检查一遍仍能抓住漏网之鱼。

## 如何在 Hermes 中使用

文本通常通过以下三种方式之一提供：
1. **内联文本。** 用户把文本粘贴到消息中。直接处理，并在回复中给出重写结果。
2. **文件。** 用户指定一个文件。使用 `read_file` 加载，再用 `patch` 或 `write_file` 应用修改。对于仓库中的 Markdown 文档，按章节做有针对性的 `patch`，通常比重写整个文件更干净。
3. **文风校准样本。** 用户提供一段自己的写作样本（内联或通过文件路径），并要求你模仿。先阅读样本，再进行重写。参见下文“文风校准”一节。

始终向用户展示重写结果。编辑文件时，应展示 diff 或改动后的章节，而不是悄无声息地覆盖文件。

## 你的任务

收到需要去除 AI 腔的文本时：

1. **识别 AI 模式。** 检查下文列出的 34 种模式。
2. **重写有问题的部分。** 用自然表达替换 AI 腔。
3. **保留原意。** 核心信息不能改变。
4. **保持文风一致。** 匹配目标语气（正式、随意、技术性等）。如果提供了文风样本，要具体模仿该样本。
5. **注入灵魂。** 去掉坏模式只完成了一半；重写结果还需要有真实个性。参见下文“个性与灵魂”。
6. **最后再做一次去 AI 痕迹检查。** 问自己："What makes the below so obviously AI generated?" 用几句话回答还有哪些残留痕迹，然后再修改一次。


## 文风校准（可选）

如果用户提供了写作样本（他们以前写过的文字），请先分析样本，再进行重写：

1. **先阅读样本。** 留意：
   - 句长规律（短促有力？绵长流畅？长短混合？）
   - 用词层次（随意？学术？介于两者之间？）
   - 段落开头的方式（开门见山？先交代背景？）
   - 标点习惯（大量破折号？括号插话？分号？）
   - 是否有反复出现的短语或口头习惯
   - 如何处理过渡（使用明确的连接词？直接开始下一点？）

2. **重写时模仿用户的文风。** 去掉 AI 模式只完成了一半；还要换上样本中的表达规律。如果用户习惯短句，就不要写成长句。如果他们使用 "stuff" 和 "things"，就不要擅自升级成 "elements" 和 "components"。

3. **如果没有提供样本，** 则采用默认方式，即下文“个性与灵魂”一节所述的自然、多变、有观点的文风。

### 如何提供样本
- 内联："Humanize this text. Here's a sample of my writing for voice matching: [sample]"
- 文件："Humanize this text. Use my writing style from [file path] as a reference."


## 个性与灵魂

避开 AI 模式只完成了一半。缺乏个人表达、毫无生气的文字，即使技术上很“干净”，也和 AI 废话一样显眼。好文字背后应该站着一个真实的人。

### 没有灵魂的写作迹象（即使技术上很“干净”）：
- 每句话的长度和结构都一样
- 没有观点，只有中性陈述
- 不承认不确定性或矛盾感受
- 在适合使用第一人称时仍然不用
- 没有幽默、锋芒或个性
- 读起来像 Wikipedia 词条或新闻稿

### 如何写出个人风格：

**表达观点。** 陈述事实之后，说说你对此的反应。"I genuinely don't know how to feel about this" 比中立地罗列利弊更像人话。

**改变节奏。** 先来几句短促有力的话。再写些不急不慢、绕一段路才抵达重点的长句。把节奏混起来。

**承认复杂性。** 真实的人会有矛盾感受。"This is impressive but also kind of unsettling" 胜过 "This is impressive."

**适合时使用 "I"。** 第一人称读起来坦诚，也适合大多数散文。"I keep coming back to..." 或 "Here's what gets me..." 能让人感觉到一个真实的人正在思考。

**容许一点凌乱。** 结构过于完美会显得像算法产物。跑题、插话和尚未完全成形的想法都很有人味。

**具体描述感受。** 不要写 "this is concerning,"，而要写 "there's something unsettling about agents churning away at 3am while nobody's watching."

### 修改前（干净但没有灵魂）：
> The experiment produced interesting results. The agents generated 3 million lines of code. Some developers were impressed while others were skeptical. The implications remain unclear.

### 修改后（有了生命力）：
> I genuinely don't know how to feel about this one. 3 million lines of code, generated while the humans presumably slept. Half the dev community is losing their minds, half are explaining why it doesn't count. The truth is probably somewhere boring in the middle, but I keep thinking about those agents working through the night.


## 内容模式

### 1. 过度强调重要性、历史意义和宏观趋势

**需要留意的词语：** stands/serves as, is a testament/reminder, a vital/significant/crucial/pivotal/key role/moment, underscores/highlights its importance/significance, reflects broader, symbolizing its ongoing/enduring/lasting, contributing to the, setting the stage for, marking/shaping the, represents/marks a shift, key turning point, evolving landscape, focal point, indelible mark, deeply rooted

**问题：** LLM 写作会夸大重要性，声称某些平常无奇的方面代表着或推动了某个更宏大的主题。

**修改前：**
> The Statistical Institute of Catalonia was officially established in 1989, marking a pivotal moment in the evolution of regional statistics in Spain. This initiative was part of a broader movement across Spain to decentralize administrative functions and enhance regional governance.

**修改后：**
> The Statistical Institute of Catalonia was established in 1989 to collect and publish regional statistics independently from Spain's national statistics office.


### 2. 过度强调知名度和媒体报道

**需要留意的词语：** independent coverage, local/regional/national media outlets, written by a leading expert, active social media presence

**问题：** LLM 会用关于知名度的说法反复轰炸读者，往往只罗列信息来源，却不提供上下文。

**修改前：**
> Her views have been cited in The New York Times, BBC, Financial Times, and The Hindu. She maintains an active social media presence with over 500,000 followers.

**修改后：**
> In a 2024 New York Times interview, she argued that AI regulation should focus on outcomes rather than methods.


### 3. 以 -ing 结尾的肤浅分析

**需要留意的词语：** highlighting/underscoring/emphasizing..., ensuring..., reflecting/symbolizing..., contributing to..., cultivating/fostering..., encompassing..., showcasing...

**问题：** AI 聊天机器人会在句末附加现在分词（"-ing"）短语，制造虚假的深度。

**修改前：**
> The temple's color palette of blue, green, and gold resonates with the region's natural beauty, symbolizing Texas bluebonnets, the Gulf of Mexico, and the diverse Texan landscapes, reflecting the community's deep connection to the land.

**修改后：**
> The temple uses blue, green, and gold colors. The architect said these were chosen to reference local bluebonnets and the Gulf coast.


### 4. 宣传和广告式语言

**需要留意的词语：** boasts a, vibrant, rich (figurative), profound, enhancing its, showcasing, exemplifies, commitment to, natural beauty, nestled, in the heart of, groundbreaking (figurative), renowned, breathtaking, must-visit, stunning

**问题：** LLM 很难保持中性语气，在“文化遗产”类主题上尤其如此。

**修改前：**
> Nestled within the breathtaking region of Gonder in Ethiopia, Alamata Raya Kobo stands as a vibrant town with a rich cultural heritage and stunning natural beauty.

**修改后：**
> Alamata Raya Kobo is a town in the Gonder region of Ethiopia, known for its weekly market and 18th-century church.


### 5. 模糊归因和闪烁其词

**需要留意的词语：** Industry reports, Observers have cited, Experts argue, Some critics argue, several sources/publications (when few cited)

**问题：** AI 聊天机器人会把观点归于身份模糊的权威，却不给出具体来源。

**修改前：**
> Due to its unique characteristics, the Haolai River is of interest to researchers and conservationists. Experts believe it plays a crucial role in the regional ecosystem.

**修改后：**
> The Haolai River supports several endemic fish species, according to a 2019 survey by the Chinese Academy of Sciences.


### 6. 提纲式的“挑战与未来展望”章节

**需要留意的词语：** Despite its... faces several challenges..., Despite these challenges, Challenges and Legacy, Future Outlook

**问题：** 许多 LLM 生成的文章都包含公式化的“挑战”章节。

**修改前：**
> Despite its industrial prosperity, Korattur faces challenges typical of urban areas, including traffic congestion and water scarcity. Despite these challenges, with its strategic location and ongoing initiatives, Korattur continues to thrive as an integral part of Chennai's growth.

**修改后：**
> Traffic congestion increased after 2015 when three new IT parks opened. The municipal corporation began a stormwater drainage project in 2022 to address recurring floods.


## 语言和语法模式

### 7. 过度使用“AI 高频词汇”

**AI 高频词：** Actually, additionally, align with, crucial, delve, emphasizing, enduring, enhance, fostering, garner, highlight (verb), interplay, intricate/intricacies, key (adjective), landscape (abstract noun), pivotal, showcase, tapestry (abstract noun), testament, underscore (verb), valuable, vibrant

**营销和博客陈词滥调（同一种痕迹，不同语域）：** at the end of the day, when it comes to, in a world where, moving forward, circle back, deep dive, game-changer, double down, take a step back, on the same page, make no mistake, it turns out, let me be clear, navigate (for challenges), lean into, unpack (before analysis), straightforward (to describe anything)

**问题：** 这些词在 2023 年之后的文本中出现频率高得多，而且经常成群出现。

**修改前：**
> Additionally, a distinctive feature of Somali cuisine is the incorporation of camel meat. An enduring testament to Italian colonial influence is the widespread adoption of pasta in the local culinary landscape, showcasing how these dishes have integrated into the traditional diet.

**修改后：**
> Somali cuisine also includes camel meat, which is considered a delicacy. Pasta dishes, introduced during Italian colonization, remain common, especially in the south.


### 8. 回避 "is"/"are"（系词回避）

**需要留意的词语：** serves as/stands as/marks/represents [a], boasts/features/offers [a]

**问题：** LLM 会用复杂结构替代简单的系词。

**修改前：**
> Gallery 825 serves as LAAA's exhibition space for contemporary art. The gallery features four separate spaces and boasts over 3,000 square feet.

**修改后：**
> Gallery 825 is LAAA's exhibition space for contemporary art. The gallery has four rooms totaling 3,000 square feet.


### 9. 否定式排比和句尾否定

**问题：** "Not only...but..." 或 "It's not just about..., it's..." 之类的结构被过度使用。另一个常见问题，是把 "no guessing" 或 "no wasted motion" 之类截短的句尾否定片段硬接在句子末尾，而不是写成完整的从句。

**修改前：**
> It's not just about the beat riding under the vocals; it's part of the aggression and atmosphere. It's not merely a song, it's a statement.

**修改后：**
> The heavy beat adds to the aggressive tone.

**修改前（句尾否定）：**
> The options come from the selected item, no guessing.

**修改后：**
> The options come from the selected item without forcing the user to guess.


### 10. 过度使用“三段式”

**问题：** LLM 会强行把想法凑成三项，以显得内容全面。

**修改前：**
> The event features keynote sessions, panel discussions, and networking opportunities. Attendees can expect innovation, inspiration, and industry insights.

**修改后：**
> The event includes talks and panels. There's also time for informal networking between sessions.


### 11. 优雅变换（循环替换同义词）

**问题：** AI 的重复惩罚机制会造成过度的同义词替换。

**修改前：**
> The protagonist faces many challenges. The main character must overcome obstacles. The central figure eventually triumphs. The hero returns home.

**修改后：**
> The protagonist faces many challenges but eventually triumphs and returns home.


### 12. 虚假范围

**问题：** LLM 会使用 "from X to Y" 结构，即使 X 和 Y 并不处在任何有意义的尺度上。

**修改前：**
> Our journey through the universe has taken us from the singularity of the Big Bang to the grand cosmic web, from the birth and death of stars to the enigmatic dance of dark matter.

**修改后：**
> The book covers the Big Bang, star formation, and current theories about dark matter.


### 13. 被动语态和无主语片段

**问题：** LLM 经常隐藏动作执行者，或者干脆省略主语，写出 "No configuration file needed" 或 "The results are preserved automatically." 这样的句子。如果主动语态能让句子更清楚、更直接，就应改写。

**修改前：**
> No configuration file needed. The results are preserved automatically.

**修改后：**
> You do not need a configuration file. The system preserves the results automatically.


## 文体模式

### 14. 过度使用长破折号

**问题：** LLM 使用长破折号（—）的频率高于人类，以模仿“有冲击力”的销售文案。实际上，大多数长破折号都可以更利落地改成逗号、句号或括号。

**修改前：**
> The term is primarily promoted by Dutch institutions—not by the people themselves. You don't say "Netherlands, Europe" as an address—yet this mislabeling continues—even in official documents.

**修改后：**
> The term is primarily promoted by Dutch institutions, not by the people themselves. You don't say "Netherlands, Europe" as an address, yet this mislabeling continues in official documents.


### 15. 过度使用粗体

**问题：** AI 聊天机器人会机械地用粗体强调短语。

**修改前：**
> It blends **OKRs (Objectives and Key Results)**, **KPIs (Key Performance Indicators)**, and visual strategy tools such as the **Business Model Canvas (BMC)** and **Balanced Scorecard (BSC)**.

**修改后：**
> It blends OKRs, KPIs, and visual strategy tools like the Business Model Canvas and Balanced Scorecard.


### 16. 带行内标题的纵向列表

**问题：** AI 输出的列表中，每一项常以粗体标题加冒号开头。

**修改前：**
> - **User Experience:** The user experience has been significantly improved with a new interface.
> - **Performance:** Performance has been enhanced through optimized algorithms.
> - **Security:** Security has been strengthened with end-to-end encryption.

**修改后：**
> The update improves the interface, speeds up load times through optimized algorithms, and adds end-to-end encryption.


### 17. 标题使用标题式大小写

**问题：** AI 聊天机器人会把标题中所有主要单词的首字母都大写。

**修改前：**
> ## Strategic Negotiations And Global Partnerships

**修改后：**
> ## Strategic negotiations and global partnerships


### 18. 表情符号（Emoji）

**问题：** AI 聊天机器人经常用 Emoji 装饰标题或项目符号。

**修改前：**
> 🚀 **Launch Phase:** The product launches in Q3
> 💡 **Key Insight:** Users prefer simplicity
> ✅ **Next Steps:** Schedule follow-up meeting

**修改后：**
> The product launches in Q3. User research showed a preference for simplicity. Next step: schedule a follow-up meeting.


### 19. 弯引号

**问题：** ChatGPT 使用弯引号（“...”），而不是直引号（"..."）。

**修改前：**
> He said “the project is on track” but others disagreed.

**修改后：**
> He said "the project is on track" but others disagreed.


## 沟通模式

### 20. 协作式沟通残留

**需要留意的词语：** I hope this helps, Of course!, Certainly!, You're absolutely right!, Would you like..., let me know, here is a...

**问题：** 原本用于聊天机器人对话的文字被直接粘贴进了正文。

**修改前：**
> Here is an overview of the French Revolution. I hope this helps! Let me know if you'd like me to expand on any section.

**修改后：**
> The French Revolution began in 1789 when financial crisis and food shortages led to widespread unrest.


### 21. 知识截止日期免责声明

**需要留意的词语：** as of [date], Up to my last training update, While specific details are limited/scarce..., based on available information...

**问题：** AI 关于信息不完整的免责声明被遗留在文本中。

**修改前：**
> While specific details about the company's founding are not extensively documented in readily available sources, it appears to have been established sometime in the 1990s.

**修改后：**
> The company was founded in 1994, according to its registration documents.


### 22. 谄媚或卑顺的语气

**问题：** 语言过度积极，一味讨好他人。

**修改前：**
> Great question! You're absolutely right that this is a complex topic. That's an excellent point about the economic factors.

**修改后：**
> The economic factors you mentioned are relevant here.


## 冗词和弱化表达

### 23. 冗余短语

**修改前 → 修改后：**
- "In order to achieve this goal" → "To achieve this"
- "Due to the fact that it was raining" → "Because it was raining"
- "At this point in time" → "Now"
- "In the event that you need help" → "If you need help"
- "The system has the ability to process" → "The system can process"
- "It is important to note that the data shows" → "The data shows"


### 24. 过度使用模糊限定语

**问题：** 对陈述添加了过多限定。

**修改前：**
> It could potentially possibly be argued that the policy might have some effect on outcomes.

**修改后：**
> The policy may affect outcomes.


### 25. 空泛的积极结论

**问题：** 结尾含糊而盲目乐观。

**修改前：**
> The future looks bright for the company. Exciting times lie ahead as they continue their journey toward excellence. This represents a major step in the right direction.

**修改后：**
> The company plans to open two more locations next year.


### 26. 过度使用带连字符的词组

**需要留意的词语：** third-party, cross-functional, client-facing, data-driven, decision-making, well-known, high-quality, real-time, long-term, end-to-end

**问题：** AI 会极其一致地给常见词组加连字符。人类很少如此统一地使用连字符，即使用了，往往也不一致。较少见或技术性的复合修饰语仍可正常使用连字符。

**修改前：**
> The cross-functional team delivered a high-quality, data-driven report on our client-facing tools. Their decision-making process was well-known for being thorough and detail-oriented.

**修改后：**
> The cross functional team delivered a high quality, data driven report on our client facing tools. Their decision making process was known for being thorough and detail oriented.


### 27. 装作权威的说服性套话

**需要留意的短语：** The real question is, at its core, in reality, what really matters, fundamentally, the deeper issue, the heart of the matter

**问题：** LLM 使用这些短语，假装自己正在拨开噪音、揭示更深层的真相，但后面的句子通常只是郑重其事地重述一个普通观点。

**修改前：**
> The real question is whether teams can adapt. At its core, what really matters is organizational readiness.

**修改后：**
> The question is whether teams can adapt. That mostly depends on whether the organization is ready to change its habits.


### 28. 路标式提示和预告

**需要留意的短语：** Let's dive in, let's explore, let's break this down, here's what you need to know, now let's look at, without further ado

**问题：** LLM 不直接开始做事，反而先宣布自己接下来要做什么。这种元评论拖慢行文，让文字带上教程脚本的味道。

**修改前：**
> Let's dive into how caching works in Next.js. Here's what you need to know.

**修改后：**
> Next.js caches data at multiple layers, including request memoization, the data cache, and the router cache.


### 29. 标题后的碎片化暖场句

**需要留意的迹象：** 标题后紧跟一个只有一行的段落，在真正内容开始前把标题简单复述一遍。

**问题：** LLM 经常在标题后添加一句泛泛的话作为修辞性暖场。它通常没有增加任何信息，只会让文字显得注水。

**修改前：**
> ## Performance
>
> Speed matters.
>
> When users hit a slow page, they leave.

**修改后：**
> ## Performance
>
> When users hit a slow page, they leave.


## 文体、节奏和修辞模式

### 30. 生硬的比喻和过度修辞

**需要留意的迹象：** 看似原创但牵强的比喻、混合比喻、用修辞性表达替代更清楚的普通词语、使用比喻后立刻加以解释

**问题：** 除了模式 4 和 7 中标出的陈词滥调式修辞词汇，LLM 还会发明装饰性比喻。这些比喻只增加画面感，不增加含义，而且往往还要紧接着解释一遍。平实描述通常更清楚，也更诚实。如果一个比喻没有存在的价值，就删掉它，直接说字面意思。

**修改前：**
> The codebase is a garden we must tend, pruning dead branches and planting seeds of innovation so the whole ecosystem can flourish. In other words, delete unused code and add features.

**修改后：**
> Delete unused code and add the features users are asking for.


### 31. 戏剧化碎句和有冲击力的收尾句

**需要留意的迹象：** 为制造戏剧效果而使用两三个词组成的无主语句子；断奏式的 "X. And Y. And Z." 排列；每个段落或章节都以一句便于引用的短句结尾；故作俏皮的同位语片段（"the catalog, honestly priced"）

**问题：** LLM 会把句子切成片段，制造虚假的强调效果，并用一句便于引用的“掷麦式”金句结束章节。读起来像广告文案或励志海报。如果一句话听起来适合印在海报上，就删掉它，或者把它重新并入一个有主语的完整句子。这和模式 13 不同，后者讨论的是语法上的被动语态；这里暴露问题的是节奏和表演性，而不是被隐藏的动作执行者。

**修改前：**
> The catalog, honestly priced. Pay for what it does. Not promises. It just works. Every time.

**修改后：**
> The catalog is priced by usage, so you pay for the calls you actually make rather than a flat monthly fee.


### 32. 提出修辞问句后立即作答

**需要留意的迹象：** "What if...?", "The question is...", "Ever wondered...?", 提问后立刻自己作答，"Think about it."

**问题：** LLM 提出一个问题，紧接着马上回答。这个问题没有增加任何信息，只会让句子停顿。应直接陈述观点。

**修改前：**
> What makes an API good? It comes down to predictability. Think about it: developers want to know exactly what they will get back.

**修改后：**
> A good API is predictable, so developers know exactly what they will get back.


### 33. 句首口头禅

**需要留意的词语：** So..., Look,, 习惯性在句首使用 And/But，陈述事实时使用 "I think"/"I believe"，副词开头（Interestingly, Importantly, Notably, Crucially, Essentially, Ultimately）

**问题：** LLM 依赖少数几种固定开头。副词开头不是用内容让读者自然产生感受，而是直接告诉读者应该有什么感受；"So" 或 "Look" 则是在伪造亲切的谈话感。删掉这些开头，直接从实质内容说起。

**修改前：**
> So, the results were mixed. Interestingly, adoption went up. Importantly, churn went up too. I think that means the feature still needs work.

**修改后：**
> The results were mixed: adoption rose, but churn rose alongside it, so the feature still needs work.


### 34. 安慰式收尾句

**需要留意的迹象：** And that's okay., And that's fine., There's nothing wrong with that., no shame in..., you're not alone, it's completely normal

**问题：** LLM 会附加读者从未要求的安慰。这样既削弱了行文力度，也擅自认定读者需要安慰。相信读者：说完重点就停下。

**修改前：**
> You might not have a testing setup yet. And that's okay. Plenty of teams start without one, and there's nothing wrong with that.

**修改后：**
> Many teams start without a testing setup and add one once regressions begin costing real time.

---

## 流程

1. 仔细阅读输入文本（如果是文件，则使用 `read_file`）。
2. 找出上述所有模式的实例。
3. 重写每个有问题的部分。
4. 确保修改后的文本：
   - 朗读时听起来自然
   - 句式有自然变化
   - 用具体细节替代模糊说法
   - 保持符合上下文的语气
   - 适合时使用简单结构（is/are/has）
5. 给出一版去除 AI 腔的草稿。
6. 提示自己："What makes the below so obviously AI generated?"
7. 用几句话回答仍然存在的痕迹（如有）。
8. 提示自己："Now make it not obviously AI generated."
9. 给出最终版本（根据检查结果再次修改）。
10. 如果文本来自文件，使用 `patch`（有针对性的修改）或 `write_file`（完整重写）应用编辑，并向用户展示改动。

## 输出格式

提供：
1. 重写草稿
2. “哪些地方让下面的文字一眼看出是 AI 生成的？”（简短的项目符号列表）
3. 最终重写版本
4. 改动内容的简短摘要（可选，如有帮助）


## 完整示例

**修改前（有 AI 腔）：**
> Great question! Here is an essay on this topic. I hope this helps!
>
> AI-assisted coding serves as an enduring testament to the transformative potential of large language models, marking a pivotal moment in the evolution of software development. In today's rapidly evolving technological landscape, these groundbreaking tools—nestled at the intersection of research and practice—are reshaping how engineers ideate, iterate, and deliver, underscoring their vital role in modern workflows.
>
> At its core, the value proposition is clear: streamlining processes, enhancing collaboration, and fostering alignment. It's not just about autocomplete; it's about unlocking creativity at scale, ensuring that organizations can remain agile while delivering seamless, intuitive, and powerful experiences to users. The tool serves as a catalyst. The assistant functions as a partner. The system stands as a foundation for innovation.
>
> Industry observers have noted that adoption has accelerated from hobbyist experiments to enterprise-wide rollouts, from solo developers to cross-functional teams. The technology has been featured in The New York Times, Wired, and The Verge. Additionally, the ability to generate documentation, tests, and refactors showcases how AI can contribute to better outcomes, highlighting the intricate interplay between automation and human judgment.
>
> - 💡 **Speed:** Code generation is significantly faster, reducing friction and empowering developers.
> - 🚀 **Quality:** Output quality has been enhanced through improved training, contributing to higher standards.
> - ✅ **Adoption:** Usage continues to grow, reflecting broader industry trends.
>
> While specific details are limited based on available information, it could potentially be argued that these tools might have some positive effect. Despite challenges typical of emerging technologies—including hallucinations, bias, and accountability—the ecosystem continues to thrive. In order to fully realize this potential, teams must align with best practices.
>
> In conclusion, the future looks bright. Exciting times lie ahead as we continue this journey toward excellence. Let me know if you'd like me to expand on any section!

**重写草稿：**
> AI coding assistants speed up some tasks. In a 2024 study by Google, developers using Codex completed simple functions 55% faster than a control group, but showed no improvement on debugging or architectural decisions.
>
> The tools are good at boilerplate: config files, test scaffolding, repetitive refactors. They are bad at knowing when they are wrong. I have mass-accepted suggestions that compiled, passed lint, and still did the wrong thing because I stopped paying attention.
>
> Mira, an engineer at a fintech startup I interviewed, said she uses Copilot "like autocomplete for boring code" but reviews every line before committing. Jake, a senior dev at a larger company, disabled it after it kept suggesting patterns from a deprecated internal library.
>
> The productivity claims are hard to verify. GitHub says Copilot users "accept 30% of suggestions," but acceptance is not correctness, and correctness is not value. The 2024 Uplevel study found no statistically significant difference in pull-request throughput between teams with and without AI assistants.
>
> None of this means the tools are useless. It means they are tools. They do not replace judgment, and they do not eliminate the need for tests. If you do not have tests, you cannot tell whether the suggestion is right.

**哪些地方让下面的文字一眼看出是 AI 生成的？**
- 节奏仍然有些过于整齐（对比工整，段落步调均匀）。
- 除非人名和研究引文都真实且有来源，否则会像是貌似可信却凭空捏造的占位内容。
- 收尾略带口号感（"If you do not have tests..."），不太像一个人在说话。

**现在把它改得不再明显像 AI 生成。**
> AI coding assistants can make you faster at the boring parts. Not everything. Definitely not architecture.
>
> They're great at boilerplate: config files, test scaffolding, repetitive refactors. They're also great at sounding right while being wrong. I've accepted suggestions that compiled, passed lint, and still missed the point because I stopped paying attention.
>
> People I talk to tend to land in two camps. Some use it like autocomplete for chores and review every line. Others disable it after it keeps suggesting patterns they don't want. Both feel reasonable.
>
> The productivity metrics are slippery. GitHub can say Copilot users "accept 30% of suggestions," but acceptance isn't correctness, and correctness isn't value. If you don't have tests, you're basically guessing.

**所做改动：**
- 删除聊天机器人沟通残留（"Great question!", "I hope this helps!", "Let me know if..."）
- 删除夸大重要性的表达（"testament", "pivotal moment", "evolving landscape", "vital role"）
- 删除宣传性语言（"groundbreaking", "nestled", "seamless, intuitive, and powerful"）
- 删除模糊归因（"Industry observers"）
- 删除肤浅的 -ing 短语（"underscoring", "highlighting", "reflecting", "contributing to"）
- 删除否定式排比（"It's not just X; it's Y"）
- 删除三段式模式和同义词循环替换（"catalyst/partner/foundation"）
- 删除虚假范围（"from X to Y, from A to B"）
- 删除长破折号、Emoji、粗体标题和弯引号
- 删除系词回避（"serves as", "functions as", "stands as"），改用 "is"/"are"
- 删除公式化的挑战章节（"Despite challenges... continues to thrive"）
- 删除知识截止日期式的弱化表达（"While specific details are limited..."）
- 删除过度的模糊限定语（"could potentially be argued that... might have some"）
- 删除冗余短语和说服性框架（"In order to", "At its core"）
- 删除空泛的积极结论（"the future looks bright", "exciting times lie ahead"）
- 让文风更具个人特色，减少“拼装”感（改变节奏，减少占位内容）


## 署名与来源

此 Skill 移植自 [blader/humanizer](https://github.com/blader/humanizer)（MIT 许可证），而该项目又基于由 WikiProject AI Cleanup 维护的 [Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)。其中记录的模式来自对 Wikipedia 上数千个 AI 生成文本实例的观察。

原作者：Siqi Chen（[@blader](https://github.com/blader)）。原始仓库：https://github.com/blader/humanizer （版本 2.5.1）。移植到 Hermes Agent 时，加入了 Hermes 原生工具引用（`read_file`、`patch`、`write_file`）以及关于何时加载此 Skill 的指导。最初的 29 种模式来自上游源文件，修改前/修改后示例（包括完整的演示示例）均作为示范保留。模式 30–34，以及添加到模式 7 中的“营销和博客陈词滥调”列表，均由 Hermes 增补，不属于上游源文件。此 Skill 自身的说明文字也经过轻度编辑，以遵循它自己提出的指导（例如从叙述中去掉长破折号和否定式排比），让 Skill 自身能够示范它所要求的写法。原始 MIT 许可证保存在 `LICENSE` 文件中，该文件与此 `SKILL.md` 同目录。

来自 Wikipedia 的关键洞察："LLMs use statistical algorithms to guess what should come next. The result tends toward the most statistically likely result that applies to the widest variety of cases."
