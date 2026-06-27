# Agent / OpenClaw 对接说明

计算器本体不内置飞书或 Telegram 机器人。频道侧只负责收图、调用计算器接口、回传结果。

推荐链路：

1. 本地或服务器启动计算器：`orc-calc.exe serve --host 127.0.0.1 --port 8765`
2. OpenClaw/Agent 收到图片后保存临时文件。
3. 适配器调用 `POST http://127.0.0.1:8765/api/v1/recognize`，或执行 `orc-calc.exe recognize image.jpg --json`。
4. 适配器把 `fields` 和 `calculation.results` 格式化后发回飞书或 Telegram。

`openclaw_http_adapter.py` 是最小示例，只依赖 Python 标准库。真实频道鉴权、消息签名、重试和日志应放在适配器层，不放进 `orc_calc/core`。

更完整的 OpenClaw + 飞书配置步骤见：

`docs/openclaw_feishu_setup.md`
