# Excalidraw 深色模式图表

要创建深色主题图表，请将一个巨大的深色背景矩形作为数组中的**第一个元素**。确保它足够大，能够覆盖任何视口：

```json
{
  "type": "rectangle", "id": "darkbg",
  "x": -4000, "y": -3000, "width": 10000, "height": 7500,
  "backgroundColor": "#1e1e2e", "fillStyle": "solid",
  "strokeColor": "transparent", "strokeWidth": 0
}
```

然后，对深色背景上的元素使用以下调色板。

## 文本颜色（深色背景上）

| 颜色 | 十六进制色值 | 用途 |
|-------|-----|-----|
| 白色 | `#e5e5e5` | 主要文本、标题 |
| 柔和色 | `#a0a0a0` | 次要文本、注释 |
| 切勿使用 | `#555` 或更深的颜色 | 在深色背景上不可见！ |

## 形状填充色（深色背景上）

| 颜色 | 十六进制色值 | 适用场景 |
|-------|-----|----------|
| 深蓝色 | `#1e3a5f` | 主要节点 |
| 深绿色 | `#1a4d2e` | 成功、输出 |
| 深紫色 | `#2d1b69` | 处理过程、特殊内容 |
| 深橙色 | `#5c3d1a` | 警告、待处理 |
| 深红色 | `#5c1a1a` | 错误、关键事项 |
| 深青绿色 | `#1a4d4d` | 存储、数据 |

## 描边和箭头颜色（深色背景上）

使用主调色板中的标准主色——它们在深色背景上足够明亮：
- 蓝色 `#4a9eed`、琥珀色 `#f59e0b`、绿色 `#22c55e`、红色 `#ef4444`、紫色 `#8b5cf6`

对于不显眼的形状边框，请使用 `#555555`。

## 示例：带标签的深色模式矩形

使用容器绑定（不要使用不起作用的 `"label"` 属性）。在深色背景上，将文本的 `strokeColor` 设置为 `"#e5e5e5"`，以确保文本可见：

```json
[
  {
    "type": "rectangle", "id": "r1",
    "x": 100, "y": 100, "width": 200, "height": 80,
    "backgroundColor": "#1e3a5f", "fillStyle": "solid",
    "strokeColor": "#4a9eed", "strokeWidth": 2,
    "roundness": { "type": 3 },
    "boundElements": [{ "id": "t_r1", "type": "text" }]
  },
  {
    "type": "text", "id": "t_r1",
    "x": 105, "y": 120, "width": 190, "height": 25,
    "text": "Dark Node", "fontSize": 20, "fontFamily": 1,
    "strokeColor": "#e5e5e5",
    "textAlign": "center", "verticalAlign": "middle",
    "containerId": "r1", "originalText": "Dark Node", "autoResize": true
  }
]
```

注意：对于深色背景上的独立文本元素，始终明确设置 `"strokeColor": "#e5e5e5"`。默认的 `#1e1e1e` 在深色背景上不可见。
