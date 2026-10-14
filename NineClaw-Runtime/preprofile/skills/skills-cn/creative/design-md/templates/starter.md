---
version: alpha
name: MyBrand
description: 用一句话描述视觉标识。
colors:
  primary: "#0F172A"
  secondary: "#64748B"
  tertiary: "#2563EB"
  neutral: "#F8FAFC"
  on-primary: "#FFFFFF"
  on-tertiary: "#FFFFFF"
typography:
  h1:
    fontFamily: Inter
    fontSize: 3rem
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  h2:
    fontFamily: Inter
    fontSize: 2rem
    fontWeight: 600
    lineHeight: 1.2
  body-md:
    fontFamily: Inter
    fontSize: 1rem
    lineHeight: 1.5
  label-caps:
    fontFamily: Inter
    fontSize: 0.75rem
    fontWeight: 600
    letterSpacing: "0.08em"
rounded:
  sm: 4px
  md: 8px
  lg: 16px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 48px
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.on-tertiary}"
    rounded: "{rounded.sm}"
    padding: 12px
  button-primary-hover:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
  card:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
    padding: 24px
---

## Overview

用一到两段描述品牌的表达方式与整体感受。它营造了怎样的氛围？用户第一眼看到时应产生怎样的情绪反应？

## Colors

- **主色（{colors.primary}）：** 用于核心文字、标题和高强调表面。
- **辅助色（{colors.secondary}）：** 用于辅助文字、边框和元数据。
- **第三色（{colors.tertiary}）：** 用于驱动交互——按钮、链接和选中状态。应谨慎使用，以保持其提示作用。
- **中性色（{colors.neutral}）：** 用于页面背景和表面填充。

## Typography

所有内容均使用 Inter。通过字重与字号建立层级，而不是更换字体。展示字号使用紧凑的字间距；正文使用默认字距。

## Layout

间距比例以 4px 为基准。组件内部间距使用 `md`（16px），组件之间的间距使用 `lg`（24px），章节间隔使用 `xl`（48px）。

## Shapes

圆角保持适度：交互元素使用 `sm`，卡片使用 `md`。`full` 仅用于头像和胶囊徽章。

## Components

- 每个屏幕只能有一个 `button-primary` 高强调操作。
- `card` 是分组内容的默认表面，默认不使用阴影。

## Do's and Don'ts

- **应当**在组件定义中使用令牌引用（`{colors.primary}`），而不是十六进制字面值。
- **不要**引入调色板以外的颜色；应先扩展调色板。
- **不要**嵌套组件变体。`button-primary-hover` 是同级项，而不是子项。
