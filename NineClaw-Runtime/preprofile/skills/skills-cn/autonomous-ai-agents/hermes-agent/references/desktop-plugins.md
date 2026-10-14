# 桌面应用 Plugins——UI Panes、Commands、Widgets

为 Hermes 桌面应用编写 plugin：statusbar item、layout pane、
command-palette command、keybind、route 和 theme。一个 plugin 就是应用在运行时加载的单个
纯 JavaScript ESM 文件——无需 build step，也无需修改 repo。
Plugin 还可以与自己的 Python backend namespace 通信
（`ctx.rest`/`ctx.socket` → `/api/plugins/<id>`）；通用 Python plugin
系统（`~/.hermes/plugins/`）另有独立文档。

完整的人类可读参考（所有 export、area payload、backend、安全性）：
`website/docs/developer-guide/desktop-plugin-sdk.md`。

## 适用场景

- 用户希望添加新的桌面 UI 元素（pane、statusbar widget、
  dashboard、command），但不想修改应用本身。
- 你希望在应用内呈现自己计算的数据（通过 gateway RPC）。

## 前提条件

- Hermes 桌面应用（由它加载 plugin；仅有 CLI/gateway 不会加载）。
- 对 `$HERMES_HOME/desktop-plugins/`（通常是
  `~/.hermes/desktop-plugins/`）拥有写权限。

## 运行方法

1. 创建 `$HERMES_HOME/desktop-plugins/<name>/plugin.js`，并以本 skill 目录中的
   `templates/plugin.js` 为模板——默认位于
   `~/.hermes/...`，使用 named profile 时则位于 `~/.hermes/profiles/<profile>/...`。
   请让 `<name>` 与 plugin `id` 保持一致。
2. 桌面应用会监视该目录：文件写入后数秒内 plugin 就会加载，此后每次保存都会在原位
   hot-reload。无需执行 reload 步骤。（若未出现，可使用备用方法：⌘K →
   **Reload desktop plugins**。）
3. 如果加载失败，应用会显示一条注明错误的 toast——修复文件后再次保存即可。

## 快速参考

唯一允许的 import 来源是 `@hermes/plugin-sdk`（以及 `react` /
`react/jsx-runtime`，它们会解析到应用自身的 React——UI 要使用
`jsx()` 调用编写，而不能用 JSX 语法；该文件不会被编译）。

- `host.state.*`——readonly reactive atom：`activeSessionId`、`cwd`、
  `gateway`、`model`、`profile`、`viewport`。在 handler 中用 `.get()` 读取，
  在 component 中用 `useValue(atom)` 读取。
- `host.request(method, params)`——gateway JSON-RPC（sessions、config、
  skills、cron——应用所用的一切）。
- `host.onEvent(type, fn)`——实时 gateway event（`'*'` 表示全部）。返回一个
  disposer。
- `host.notify({ kind, message })`、`host.navigate(path)`、`host.logs(...)`、
  `host.status()`、`haptic('tap')`。
- `ctx.register({ id, area, order?, render?, data? })`——贡献 UI。
  关键 area：`'statusBar.right'`/`'statusBar.left'`（chip）、
  `'panes'`（layout zone——设置 `title` 和
  `data: { placement, dock?, width?, height? }`；pane 会自动加入匹配的
  zone）、`PALETTE_AREA`（⌘K command）、`KEYBINDS_AREA`（可重新绑定的
  action）。
- Pane placement：`placement: 'left'|'right'|'bottom'|'main'` 是
  semantic role——pane 会与相同 role 的现有 pane 堆叠为 tab。
  如果希望落到特定 EDGE，请改为添加 `dock: { pane, pos }`——这与将 pane 拖到 drop chip 上是同一种操作。
  `pane` 可以是任意 pane id
  （`workspace` 是主 thread；还包括 `sessions`、`terminal`、`files`、
  `review`、`logs`），`pos` 可以是 `'top'|'bottom'|'left'|'right'|'center'`。
  例如，“位于对话下方”=`dock: { pane: 'workspace', pos: 'bottom' }`
  ——请声明一个 `height`（例如 `'200px'`），以免它占据半个 zone。
- 完整 PAGES：注册 `area: ROUTES_AREA`，并提供 `data: { path: '/my-page' }`
  和 `render`——page 会像任何内置 view 一样挂载到 workspace（main）pane 中。
  可通过 sidebar nav row 访问它：
  `ctx.register({ id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/my-page', label: 'My Page', codicon: 'project' } })`
  （显示在 Artifacts 下方，并在进入该 route 时高亮）——也可以再添加一个
  `PALETTE_AREA` command 来调用 `host.navigate('/my-page')`，或只使用后者。
- `ctx.storage.get/set/remove`——限定在你的 plugin namespace 内的持久化。
- `ctx.i18n.register({ en, ja, ... })`——随 plugin 提供你自己的 locale bundle，
  scope 仅限该 plugin（绝不要编辑 core `en.ts`）。值可以是 literal string 或
  interpolator function；nested tree 通过 dot-path 寻址。在 component 中用
  `usePluginI18n(id)` 响应式读取，它返回 `t('key', ...args)`
  （切换 locale 时会重新 render）；也可在 handler/store 中通过 `ctx.i18n.t` 读取。
  解析顺序依次为应用当前 locale、你的 `en`、原始 key。
- 数据：`useQuery`/`useMutation`/`useQueryClient`/`queryClient`（应用唯一的
  React Query client——cache、dedupe、`refetchInterval`、invalidate 均与 core 一致；
  绝不要手写 poll loop），另有 `atom`/`computed` 用于 plugin-local state。
- Backend：如果 plugin 附带 Python `plugin_api.py`（位于
  `~/.hermes/plugins/<id>/dashboard/` 下，manifest 为 `"api": "plugin_api.py"`），可通过
  `ctx.rest('/path', { method?, body?, timeoutMs? })` 访问，并通过其实时版本
  `ctx.socket('/events', onMessage)` 访问——两者在构造时都限定在 `/api/plugins/<id>` 下
  （拒绝 traversal）。`ctx.socket` 在 OAuth
  remote 上是 **no-op**，因此始终要保留 polling fallback。只有当 plugin 位于
  `plugins.enabled` 中（该项在 `config.yaml` 内）时才会 import Python backend（这与应用内的
  enable toggle 相互独立）。Gateway 范围的数据请改用 `host.request` /
  `host.onEvent`。
- `Contribute`（mount-scoped）：在 component 内 render
  `jsx(Contribute, { area, id, children })`，这样 page 自有的 chrome（例如
  `TITLEBAR_AREAS.center` 中的 titlebar control）会在 page unmount 时一同离开——
  `ctx.register` 用于永久 contribution。
- 在 default export 上设置 `defaultEnabled: false` 可发布一个 opt-in plugin：它会
  出现在 Settings → Plugins 的清单中，但在用户手动打开前保持关闭。
- 用户通过 Settings → Plugins 管理 plugin（实时 enable/disable、显示
  folder）。被禁用的 plugin 在重启后仍保持禁用——不要与此设置对抗；用户已经关闭了你的 plugin。
- UI：可直接 import 应用的 design language——`Button`、`Input`、
  `Textarea`、`Select*`、`Switch`、`Checkbox`、`SegmentedControl`、`Tabs*`、
  `Dialog*`、`ConfirmDialog`、`DropdownMenu*`、`ContextMenu*`、`Popover*`、
  `Tip`/`Tooltip*`、`Badge`、`Kbd`/`KbdGroup`、`SearchField`、`ScrollArea`、
  `Separator`、`Skeleton`、`GlyphSpinner`、`EmptyState`、`ErrorState`、
  `CopyButton`、`StatusDot`、`LogView`、`Codicon`、`DecodeText`，以及 `cn`
  和 `icons.*`。优先使用它们而不是手写 element，使 plugin 看起来像原生功能；
  样式使用 theme var，绝不要硬编码颜色。

## 操作流程

1. 选择简短的 kebab-case `id`；folder 名必须与其一致。
2. 从 `templates/plugin.js` 开始；保留 default export 的结构
   （`{ id, name, register(ctx) }`）。
3. 对于 pane，注册 `area: 'panes'`，为其提供 `placement` hint，并让
   `render` 返回你的 component——应用会自动把它放入合理的 zone；之后用户可将其拖到任意位置。
4. 使用 `host.request` 获取数据和/或通过 `host.onEvent` 订阅；
   poll 间隔绝不要短于数秒。
5. 使用文件工具写入文件，然后请用户从 ⌘K 运行
   **Reload desktop plugins**。

## 易踩坑点

- 绝不要硬编码颜色或背景（`#000`、`black`、`rgb(...)`）。Pane
  已经位于应用的 editor background 上——不要设置背景，其余内容一律使用 theme variable：
  `var(--ui-text-secondary)`、`var(--ui-text-quaternary)`、`var(--ui-stroke-secondary)`、
  `var(--ui-accent)`。进行 canvas 绘制时，用
  `getComputedStyle(canvas).getPropertyValue('--ui-accent')` 解析一次即可。
- 只能引用已经 import 的内容——忘记 import 的 component
  （例如 `StatusDot`）会在 render 时触发 ReferenceError。仔细检查 `jsx()` 调用中的每个
  identifier 是否都出现在 import 行中。
- Canvas pane 必须通过 `ResizeObserver` 跟踪其 container，
  并重新调整 canvas 尺寸（修改 width/height attribute，而不只是 CSS）——pane 会频繁调整大小
  （拖动 sash、切换 layout）；只在 mount 时确定尺寸会留下空白或造成模糊缩放。
- JSX 语法无法 parse——该文件未经编译便直接加载。请使用
  `jsx('div', { children: ... })`，它来自 `react/jsx-runtime`。
- 除 `@hermes/plugin-sdk`、`react` 和
  `react/jsx-runtime` 外不要 import 任何内容；其他 specifier 无法 resolve。
- Handler 必须以 imperative 方式读取 state（`$atom.get()`），绝不能从 render
  closure 读取——否则快速 event 会看到过时值。
- 保持 component 小巧；只在实际 render 该值的 leaf 中进行订阅（`useValue`）。

## 验证

- 执行 **Reload desktop plugins** 后，plugin UI 会出现。
- 不应出现错误 toast（“Plugin <name> failed to load”）；如果出现，其中的
  message 会说明失败原因——修复后重新加载。
- 对于 pane：新的 zone 清晰可见，并且能像任何 core pane 一样拖动。
