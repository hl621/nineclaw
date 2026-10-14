# TUI 小组件 — Ink TUI 停靠区的实时面板

为 Hermes TUI（`hermes --tui`）编写小组件应用：可以是停靠在状态栏上方、
便于快速浏览的常驻面板，也可以是独占键盘输入的模态浮层。
小组件是由 TUI 在启动时加载的普通 ESM 文件 — 无需构建步骤，也无需
更改仓库。此技能不涵盖 desktop-app 或 web-dashboard
小组件。

## 适用场景

- 用户要求在 TUI 中显示实时面板（行情滚动条、时钟、倒计时、
  状态卡片、由 API 提供数据的读数面板）。
- 用户希望把自定义模态工具（选择器、计算器、查看器）绑定到
  斜杠命令。

## 前提条件

- 必须正在使用 TUI（`hermes --tui`）。小组件不会在
  classic CLI 或消息平台中渲染。
- 需要联网的小组件必须具备其 API 所需的凭据；获取数据失败时
  必须进入错误阶段，绝不能导致崩溃。

## 运行方式

1. 使用 `write_file` 创建 `~/.hermes/tui-widgets/<name>.mjs`（完整且可工作的
   小组件请参阅 `templates/clock.mjs`）。
2. 如果 TUI 正在运行，它会在约一秒内热加载该文件（系统会监视
   widgets 目录）；`/widgets-reload` 可强制重新扫描。
3. 小组件的 id 会自动成为其斜杠命令（`/<id>`），其 `help` 会显示在 `/`
   补全弹窗中。无需、也不存在其他注册步骤。
4. 自动打开（无需命令）：在 `register(sdk)` 末尾调用
   `sdk.openWidget(app, app.init(''))` — 文件一经加载，小组件就会自行停靠。
   仅当用户明确要求时才这样做；请注意，每次执行 `/widgets-reload` 时它都会重新停靠。

## 快速参考

小组件文件默认导出 `register(sdk)`：

```js
export default function register(sdk) {
  const { Box, Text, defineWidgetApp, h } = sdk

  defineWidgetApp({
    id: 'clock',                    // slash command name
    help: 'live clock in the dock', // `/` completion metadata
    mode: 'ambient',                // 'ambient' docks; 'modal' takes input
    init: arg => ({ label: arg.trim() || 'UTC' }),   // null = print usage
    reduce: (state, { ch, key }) => (key.escape || ch === 'q' ? null : state),
    render: ({ state, t }) => h(sdk.Dialog, { width: 24 }, h(Text, { color: t.color.label }, state.label))
  })
}
```

`sdk` 包含：`defineWidgetApp`、`openWidget`、`updateWidget`、`isCtrl`、
`React`、`h`（createElement — .mjs 中不能使用 JSX）、组件 `Box`、`Text`、
`Dialog`、`Overlay`、`WidgetGrid`、`GridAreas`，以及加载组件 `Shimmer`、
`ShimmerRows`、`useShimmerPhase` — 加载阶段请使用 `ShimmerRows`，
不要只显示一行普通的“loading…”。

展开/折叠：`sdk.Accordion` — 与会话面板中 tool/skill 区域使用的是同一个基础组件。
`h(Accordion, { t, title: 'details', count: 3,
defaultOpen: false }, body)` 通过 CLICK 切换（这对不接收按键的 ambient 小组件
也有效）；modal 应用也可以传入 `open` + `onToggle`，改由 reducer state 控制。

稳定尺寸（卡片在刷新时绝不能改变大小）：

- 为 `Dialog` 设置显式 `width`；图表本身会严格返回你要求的
  `width`（历史数据尚未积累完成时，较短的序列会在左侧补齐）。
- 为动态数字补齐宽度：`String(v).padStart(6)` — 从 `51 ms` 变为 `112 ms` 时
  不能改变行长度。
- 每个阶段的行数都应保持不变；替换内容，而不是改变结构。

图表（纯字符串构造器 — 使用主题色调为结果着色）：

- `sdk.sparkline(series, width?)` → `▂▃▅▇█▆` 单行趋势图
- `sdk.sparkRows(series, width, rows)` → 多行柱状图（顶行
  在前）— 呈现任务控制面板风格；更高的单元格可提高分辨率
- `sdk.gauge(ratio, width)` → `█████░░░` 用于表示 0..1 数值的填充条
- `sdk.hbars(values, width)` → 水平条形图，每个值对应一个条形，
  末端精度为八分之一方块，并按最大值缩放

在组件 state 中维护滚动序列（每次刷新时推入一个值，最多保留约 120 个样本），
仪表板面板使用 `sparkRows` 渲染，单行内容使用 `sparkline`。

核心约定：

- `mode: 'ambient'` — 不捕获输入，由命令切换显示状态；`render`
  返回 CARD（通常为 `Dialog`），绝不能返回 `Overlay`。通过 `zone` 决定位置 — 每个区域都会预留实际空间（任何内容都绝不会
  覆盖 transcript）：
  - 停靠区（chrome 行）：`dock-top`（顶部状态栏下方）、
    `dock-bottom`（默认 — 底部状态栏上方）。
  - 侧栏（transcript 两侧的列；文本会绕开并重新排版）：
    `top-left`、`top-right`、`bottom-left`、`bottom-right` — 角落名称
    用于选择侧栏方向及其顶部/底部锚点。在 app 上将 `width` 设置为
    卡片宽度（应与 Dialog 宽度一致；默认为 44）— 侧栏会准确预留
    相同数量的列。
  将用户的描述映射到最接近的区域：“top right”→ `top-right`，
  “above/next to the status bar”→ 停靠区。侧栏适合窄卡片
  （约 30–46 列）；全宽或矮而宽的内容应放在停靠区。
- `mode: 'modal'`（默认）— 独占每一次按键；`reduce` 返回下一个
  state、返回同一个引用以吞掉按键，或返回 `null` 以关闭；`render`
  使用 `Overlay` 包裹内容以决定位置。
- 异步数据：从 `init` 发起获取请求，并通过
  `sdk.updateWidget(app, fn)` 提交结果 — 如果小组件已关闭，它不会执行任何操作，
  因此迟到的响应绝不可能使其重新出现。
- 动画：在组件内部通过 `React.useState` +
  `React.useEffect` 管理计时器（参阅模板）；时间间隔应保持 ≥ 250ms。
- 颜色：始终使用主题色调（`t.color.primary/label/muted/ok/error/…`），
  绝不硬编码十六进制颜色 — 小组件必须兼容 `/skin` 以及浅色/深色主题。

## 操作流程

1. 选择 `id`、`mode` 和 state 结构；确保 state 可序列化。
2. 以模板为基础编写文件；通过 `init` + `updateWidget` 接入数据。
3. 使用 `/<id>` 启动（写入后会热加载）；再次执行 `/<id>` 可关闭
   ambient 小组件。
4. 迭代：编辑文件 — 保存时会热重载（以最后写入者为准，新定义会遮蔽旧定义）。
   再次执行 `/<id>` 以重新挂载。

## 常见陷阱

- `.mjs` 中不能使用 JSX，也不能直接 import — 所有内容都来自 `sdk`
  参数；使用 `h(...)` 构建元素。
- 不要发布没有关闭方式的 modal（`Esc`/`q` 应返回 `null`）。
- Ambient 小组件必须保持紧凑（不超过约 6 行）— 停靠区位于
  transcript 与状态栏之间。
- 如果 `register()` 抛出异常，系统会记录日志并跳过该组件；若小组件始终没有出现，请检查
  `~/.hermes/logs/tui_gateway_crash.log`。

## 验证

运行 `/widgets-reload` — transcript 中的消息行必须在
`loaded:` 下列出该文件。然后执行 `/<id>`：ambient 小组件会停靠在右侧、
状态栏上方，同时 composer 仍可继续接收输入；再次执行 `/<id>`
会将其移除。
