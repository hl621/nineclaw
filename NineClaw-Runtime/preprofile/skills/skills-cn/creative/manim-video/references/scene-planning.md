# 场景规划参考

## 叙事弧结构

### 发现弧（最常用）
1. 引子——提出一个问题或展示令人意外的结果
2. 直觉——建立视觉层面的理解
3. 形式化——引入方程或算法
4. 揭示——呈现“恍然大悟的时刻”
5. 延伸——探讨其影响或推广

### 问题—解决方案弧
1. 问题——哪里出了问题
2. 失败的尝试——显而易见的方法行不通
3. 关键洞见——真正有效的思路
4. 解决方案——将其实现
5. 结果——展示改进

### 对比弧
1. 铺垫——介绍两种方法
2. 方法 A——其工作原理
3. 方法 B——其工作原理
4. 对照——二者的差异
5. 结论——哪一种更好

### 逐步构建弧（架构/系统）
1. 组件 A——第一部分
2. 组件 B——第二部分
3. 连接——它们如何交互
4. 扩展——加入更多部分
5. 全貌——拉远视角

## 场景转场

### 干净切换（默认）
```python
self.play(FadeOut(Group(*self.mobjects)), run_time=0.5)
self.wait(0.3)
```

### 延续元素
保留一个元素，其余元素淡出。下一个场景开始时，该元素仍显示在屏幕上。

### 变换桥接
让场景以某个形状结束，并在下一个场景开始时对其进行变换。

## 跨场景一致性

```python
# Shared constants at file top
BG = "#1C1C1C"
PRIMARY = "#58C4DD"
SECONDARY = "#83C167"
ACCENT = "#FFFF00"
TITLE_SIZE = 48
BODY_SIZE = 30
LABEL_SIZE = 24
FAST = 0.8; NORMAL = 1.5; SLOW = 2.5
```

## 场景检查清单

- [ ] 已设置背景颜色
- [ ] 每段动画都有字幕
- [ ] 每次揭示后都有 `self.wait()`
- [ ] 文本靠边定位时的 buff >= 0.5
- [ ] 文本无重叠
- [ ] 使用颜色常量（而非硬编码）
- [ ] 已应用不透明度分层
- [ ] 场景结束时干净退出
- [ ] 同时可见的元素不超过 5–6 个

## 时长估算

| 内容 | 时长 |
|---------|----------|
| 标题卡 | 3–5 秒 |
| 概念介绍 | 10–20 秒 |
| 方程揭示 | 15–25 秒 |
| 算法步骤 | 5–10 秒 |
| 数据对比 | 10–15 秒 |
| “恍然大悟的时刻” | 15–30 秒 |
| 总结 | 5–10 秒 |

## 规划模板

```markdown
# [Video Title]

## Overview
- **Topic**: [Core concept]
- **Hook**: [Opening question]
- **Aha moment**: [Key insight]
- **Target audience**: [Prerequisites]
- **Length**: [seconds/minutes]
- **Resolution**: 480p (draft) / 1080p (final)

## Color Palette
- Background: #1C1C1C
- Primary: #58C4DD -- [purpose]
- Secondary: #83C167 -- [purpose]
- Accent: #FFFF00 -- [purpose]

## Arc: [Discovery / Problem-Solution / Comparison / Build-Up]

## Scene 1: [Name] (~Ns)
**Purpose**: [one sentence]
**Layout**: [FULL_CENTER / LEFT_RIGHT / GRID / PROGRESSIVE]

### Visual elements
- [Mobject: type, position, color]

### Animation sequence
1. [Animation] -- [what it reveals] (~Ns)

### Subtitle
"[text]"
```
