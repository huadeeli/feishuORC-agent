# Legacy OpenClaw Protection Record

这个新项目只负责飞书原生机器人部署。OpenClaw 保护记录继续以旧项目为准。

本项目的保护边界：

- 不修改旧 ORC 项目。
- 飞书适配层只调用本项目内的 ORC CLI。
- 不在飞书适配层直接导入 ORC 核心、OCR 或 API 模块。
