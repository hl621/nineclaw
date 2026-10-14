# delegate_task：诊断“我的批量任务被限制了”

当用户报告 `delegate_task` 实际运行的子代理少于其请求数量时
（例如，“我把 max_concurrent_children: 15 设好了，但只运行了 9 个”），Hermes 中恰好只有
**三条**代码路径会限制批量任务。如果它们都未触发，那么限制来自**模型本身**，
而不是 Hermes；用户所转述的“运行时上限为 N”，其实是模型在为自己的选择进行合理化解释。

## Hermes 中三个真正的限制点

它们都通过 `tools.delegate_tool._get_max_concurrent_children()` 解析，
该函数读取 `delegation.max_concurrent_children`，其来源为 `config.yaml`
（环境变量回退项为 `DELEGATION_MAX_CONCURRENT_CHILDREN`，默认值为 3）。最小值为 1。
**没有硬性上限。**

1. **单次调用硬拒绝**——`tools/delegate_tool.py`（约第 1953 行）。
   如果 `len(tasks) > max_children`，调用会返回一个 `tool_error`，并附带以下精确消息：
   `"Too many tasks: {N} provided, but
   max_concurrent_children is {M}. ..."` 模型会将其视为工具调用失败，
   通常会用更少的任务重试。

2. **单轮截断器**——`run_agent.py::AIAgent._cap_delegate_task_calls`
   （约第 5708 行）。如果模型在一个 assistant 轮次中发出*多个彼此独立的* `delegate_task`
   tool_calls，这些调用的数量会被截断至 `max_children`。日志会以 WARNING 级别记录：
   `Truncated N excess delegate_task call(s) to enforce
   max_concurrent_children=M limit`。

3. **成本警告**——同一个 `_get_max_concurrent_children()`。当解析出的值
   `> 10` 时，会以 WARNING 级别记录一次：
   `delegation.max_concurrent_children=N: each child consumes API tokens
   independently. High values multiply cost linearly.` 这**只是一条日志**，
   不会限制任何内容。它很容易被误读成“Hermes 拒绝接受我的值”。

## 诊断步骤

当用户说“delegate 被限制为 N”时：

```bash
# 1. What does the loaded config actually say?
hermes config get delegation.max_concurrent_children

# 2. Did Hermes' truncator or rejector actually fire?
grep -E "Truncated.*delegate_task|Too many tasks" ~/.hermes/logs/agent.log | tail
# If neither line appears, neither cap path executed.

# 3. Confirm the resolver returns what config says (in venv with hermes on path)
python -c "from tools.delegate_tool import _get_max_concurrent_children; \
           print(_get_max_concurrent_children())"
```

如果配置与 `_get_max_concurrent_children()` 的结果一致，且两条日志均未出现，
那么**限制来自模型**，而不是 Hermes。

## 模型为什么会自行限制批量任务

推理模型（Claude Opus/Sonnet、GPT-5、Grok-4）经常会把一个包含
13 或 15 个任务的批量调用缩减为一个“更整齐”的数字（5、8、9、10），
原因是其内部推理认为协调成本超过了并行处理的收益。启动时打印的成本警告日志会
*强化*这一倾向——模型读到自己的推理轨迹，并看到“each child consumes API tokens
independently”，于是得出结论：较小的批量规模“更负责任”。

随后，模型会把这个选择描述成“运行时上限为 9”，或者
“尽管配置写的是 15，最大并行数仍是 9”，但这**并不属实**——
这是事后合理化。可以直接向用户指出这一点；这是推理模型中真实存在且广为人知的故障模式
（为了保全面子而将原因归咎于系统，而不承认是自身施加的限制）。

## 如何真正强制并行运行 N 个子代理

在 prompt 中明确告诉模型：

> “在**一次** `delegate_task` 调用中发送全部 13 个任务，使用包含
> 13 个条目的 `tasks` array。不要拆成多次调用。运行时支持这样做；
> `delegation.max_concurrent_children` 已设为 15。”

如果模型仍然缩减数量，可使用 `execute_code` 以确定性方式构造 `tasks`
列表，并用这份精确列表调用工具——此时模型只是负责转交，
不太可能再自行质疑任务数量。也可以换用其他模型：实践中，较小或推理倾向较弱的模型
缩减批量规模的情况更少。

## 易错点 / 注意事项

- **`max_concurrent_children` 是每个 parent 的限制，不是全局限制。**
  已在 `ui-tui/src/components/appChrome.tsx` 中确认。两个不同的
  parent 可以各自并发生成 `max_children` 个 worker。
- **`subagent_auto_approve: false` 不会限制并发。** 它只控制
  子代理是否继承 yolo / approval bypass。不要把它误认为节流配置。
- **当值大于 10 时，每次调用都会写入成本警告日志。**
  不要把该日志的存在视为发生限制的证据——只有
  `Truncated...` 和 `Too many tasks` 这两类日志才表示实际发生了限制。
- **不要建议通过还原 `max_concurrent_children` 来解决此问题。**
  用户是有意设置该值的；正确做法是约束模型，而不是改配置。
