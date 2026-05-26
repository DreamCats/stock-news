# Opinion Workflow 设计备忘

## 目标

`sn analyze opinion` 负责把已抽取的推荐消息归并成推荐人的观点链。

核心目标：

- 快速增量处理新增推荐消息。
- 保持同一发送人内部的观点顺序语义。
- 避免把全量消息和全量历史直接送给 LLM。
- 只在少数疑难场景使用更慢的思考链。

## 当前基线

当前实现采用快速批量路径：

```text
按 message_id 去重后的新增推荐
→ 按发送人分组并发
→ 同一发送人内部按 batch 顺序处理
→ 每批调用 fast opinion batch
→ 批量失败或漏项时单条兜底
```

默认参数：

```text
disable_thinking = true
batch_size = 16
history_limit = 80
message_char_limit = 1500
```

## 后续策略

建议把观点链做成三层：

```text
fast opinion batch:
  disable_thinking = true
  batch_size = 16
  输出 confidence + candidate_existing_topic

local risk detector:
  如果高风险 / 低置信度 / 主题近似冲突，则进入复核

slow opinion review:
  disable_thinking = false
  单条复核
  只处理少数 case
```

## Risk Detector 条件

本地规则只做分流，不直接替代 LLM 判断。

建议触发慢速复核的条件：

- `confidence < 0.75`
- `update_type` 属于 `revise` / `reverse` / `withdraw`
- 当前 `stance` 和同 topic 历史观点明显冲突
- `topic_key` 和历史主题高度相似但不完全一致
- 批量返回缺失、index 错位、JSON 修复后仍不完整

主题近似冲突示例：

```text
CPU
国产CPU
服务器CPU
CPU虚拟化
```

这类主题可能需要归并，也可能代表不同投资线索。默认快速路径容易拆散或误并，适合进入单条复核。

## Prompt 输出扩展

后续 `opinion_batch` 可以增加字段：

```json
{
  "index": 1,
  "topic_key": "CPU",
  "candidate_existing_topic": "国产CPU",
  "stance": "bullish",
  "update_type": "supplement",
  "confidence": 0.82,
  "summary": "一句话观点摘要"
}
```

字段含义：

- `confidence`：模型对本条观点归并判断的置信度。
- `candidate_existing_topic`：如果模型认为当前消息和历史某个 topic 相关，填历史 topic；否则填空字符串。

## 取舍

不建议全量开启思考链。

原因：

- 大多数观点只是 `new` / `reinforce` / `supplement`。
- 输出是短结构化 JSON，不需要长推理。
- 全量 thinking 会显著拖慢盘中 workflow。
- 低风险样本占多数，应走快速路径。

慢速复核只用于少数影响较大的判断，例如反转、修正、撤回和主题近似冲突。
