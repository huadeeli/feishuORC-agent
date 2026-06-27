# 项目保护记录

记录时间：2026-06-10

## 2026-06-10 云端优先与便携部署修复

- 旧项目功能基准固定为 `E:\AI\废纸专用ORC飞书部署`；当前开发和运行项目固定为 `D:\AIProject\feishuORC`。
- 飞书默认使用 `ORC_OCR_MODE=auto`：先调用云端 `PP-OCRv5`，Token 为空、超时、报错、返回 0 行或缺少关键字段时，自动回退本地 `PP-OCRv5 mobile`。
- 云端 Token 只允许写入便携运行目录的 `app\.env`，源码目录不得保存真实密钥。Token 可以后期填写，重启托盘即可生效，不需要重新构建。
- OCR 由托盘启动的本地 HTTP 服务常驻并预热，本地 Paddle worker 在服务生命周期内复用，不再为每张图片重新加载模型。
- `orc-calc-cli.exe`、OCR worker、OCR 服务和飞书机器人子进程均采用无控制台启动方式，识别过程中不得闪现黑框。
- 成功结果必须同时具备毛重、皮重、单价、结算重量、税费。OCR 0 行、引擎异常或任一关键字段缺失均不得发送成功卡片。
- 本地正式回退固定使用 `PP-OCRv5_mobile_det` 和 `PP-OCRv5_mobile_rec`；server 模型只保留给诊断模式。
- 日志必须记录请求模式、实际选中模式、实际模型、是否回退、每次尝试耗时和总耗时；日志采用轮转，避免无限增长。
- 飞书 SDK 日志默认固定为 `WARNING`，不得记录 WebSocket access key、ticket 或完整连接 URL。
- 飞书托盘使用 Windows 单实例互斥锁，禁止重复启动机器人。窗口右上角 X 仍只隐藏，只有托盘菜单“退出”才停止机器人和 OCR 服务。
- 便携包必须包含 `orc-calc.exe`、`orc-calc-cli.exe`、`feishu-bot.exe`、`feishu-bot-tray.exe`、`ocr-runtime`、mobile 模型缓存、运行脚本和 `app\.env`，属于完整离线便携版，不是只含启动器的精简包。

### 本次发布验收

- 完整备份：`D:\AIProject\feishuORC-backup-20260610-145920`。
- 自动化测试：63 项全部通过。
- 六张历史图片均由 `PP-OCRv5 mobile` 识别出毛重、皮重、单价、结算重量、税费五个字段。
- 指定图片税费识别为 `915.28`。
- Token 为空时，`auto` 模式先检查云端配置并自动回退 `local-fast`；部署态响应记录两次尝试、实际模型和总耗时。
- mobile 预热约 30-45 秒，预热后的历史图片单张约 19-27 秒；原 server 模型实测约 141 秒且漏税费。
- 最终运行进程数量为：一个 `feishu-bot-tray.exe`、一个 `feishu-bot.exe`、一个 `orc-calc.exe`。
- 严格单实例复验：再次启动 `feishu-bot-tray.exe` 后进程数仍为 1，第二个启动进程立即退出且不弹阻塞提示框。
- 运行日志中的历史 access key 和 ticket 已脱敏，最终 SDK `WARNING` 配置不再写入完整连接 URL。

## 当前可用状态

- 当前主项目目录：`D:\AIProject\feishuORC`
- 源码目录：`D:\AIProject\feishuORC\source`
- 便携运行目录：`D:\AIProject\feishuORC\app`
- 历史旧 E 盘 ORC 项目：仅作历史来源，不作为运行依赖；确认 D 盘运行正常后可删除或格式化。
- 飞书机器人：`废纸ORC机器人`
- 飞书长连接：已验证可以收到消息。
- 本地 OCR：D 盘便携运行目录已自带 `app\ocr-runtime` 和 `app\ocr_cache`；源码目录如需重新测试或打包，需要在本机重建 Python/OCR 开发环境。
- 云端 OCR：配置已检查，可通过云端启动脚本使用。
- 飞书图片识别：已能接收截图、识别并回复计算结果。
- 飞书随图文字：支持 `手续费15，中介费3元` 这类补充字段。
- 飞书卡片输出：识别/文字计算结果默认使用聊天消息卡片，展示客户手续费、客户中介费、收厂钱、转客户钱计算过程；卡片失败自动回退纯文本。
- 飞书识别结果展示：图片结果卡和纯文本回退会显示供应商、日期、车牌；这些字段从 OCR 原始文本中提取，仅用于展示，不参与公式计算。
- 建辉新图展示：支持 `发货单位` 作为供应商、`供货日期` 作为日期；图片 `结算金额/结算金` 会用于校验收厂钱，未识别到结算金额也显示验证不通过；`含税金额` 不作为收厂钱验证依据。
- 飞书卡片视觉重点：转客户钱名称和结果使用红色高亮；手续费、中介费、客户手续费、客户中介费使用蓝色普通文字，不做高亮。
- 飞书费用表单：可启用 `ORC_FEISHU_IMAGE_WORKFLOW=form`，图片仍从聊天框上传，机器人发送费用输入卡片；点击“识别并计算”后再 OCR 和计算，优先更新同一张卡片，失败回退为新结果卡或纯文本。
- 飞书卡片表单实测：已完成飞书开放平台卡片回调配置，聊天上传图片后显示费用输入卡，填写手续费/中介费并点击“识别并计算”可成功识别和输出结果。
- 飞书托盘后台：已新增，窗口 X 只隐藏，不关闭机器人。

## 旧项目托盘记录来源

- 旧项目 `orc_calc/tray_app.py`：网页计算器托盘实现，关闭浏览器不退出服务。
- 旧项目 `docs/openclaw_feishu_setup.md`：记录 `orc-calc.exe` 负责托盘和网页。
- 新项目 `feishu_bot/tray_app.py`：飞书机器人托盘实现，状态窗口 X 只隐藏，不退出机器人。

## 运行方式

PowerShell 中必须带 `.\` 运行当前目录脚本：

```powershell
cd "D:\AIProject\feishuORC\source"
.\run_feishu_bot_local.bat
```

或：

```powershell
cd "D:\AIProject\feishuORC\source"
.\run_feishu_bot_cloud.bat
```

同一个飞书机器人一次只开一个窗口，本地和云端不要同时运行。

日常建议使用托盘版：

```powershell
cd "D:\AIProject\feishuORC\source"
.\run_feishu_bot_tray_local.bat
```

或：

```powershell
cd "D:\AIProject\feishuORC\source"
.\run_feishu_bot_tray_cloud.bat
```

托盘版会显示状态窗口。点窗口右上角 X 只隐藏到系统托盘，机器人继续后台运行；真正退出请右键托盘图标选择“退出”。

## 计算口径

- `司磅重量 = 毛重 - 皮重`
- `客户手续费 = 司磅重量 * 手续费`
- `客户中介费 = 司磅重量 * 中介费`
- `收厂钱 = 单价 * 结算重量 - 税费`
- `转客户钱 = 收厂钱 - 客户手续费`

中介费继续计算和展示，但不再从“转客户钱”里扣除。

## 保护规则

- 不依赖历史旧项目目录；旧 E 盘项目可作为备份，确认 D 盘运行正常后可格式化。
- 飞书机器人和 ORC 后续修改只改 `D:\AIProject\feishuORC\source`。
- 飞书适配层只通过 CLI 调用 ORC，不直接导入 `orc_calc/core`、`orc_calc/ocr` 或 `orc_calc/api`。
- 程序和启动脚本不能写死旧项目路径。
- 飞书下载图片、日志和临时文件只放在 `runtime/feishu`。
- 飞书卡片表单会话只放在 `runtime/feishu/card_sessions`。
- 修改公式、字段解析、本地/云端启动脚本后，必须先跑保护检查。
- 修改托盘启动器后，必须确认窗口关闭动作为隐藏，不是退出。
- 修改飞书输出样式后，必须确认卡片失败会自动回退纯文本。
- 修改飞书结果展示后，必须确认供应商、日期、车牌仍在卡片和纯文本回退中显示，且不参与金额公式。
- 修改建辉字段或结果展示后，必须确认收厂钱只与图片 `结算金额/结算金` 校验，校验只用于展示，不参与公式；未识别到结算金额必须显示验证不通过。
- 修改飞书卡片样式后，必须确认转客户钱仍为红色高亮，手续费和中介费仍为蓝色普通文字。
- 修改飞书卡片按钮或输入框后，必须确认 `ORC_FEISHU_IMAGE_WORKFLOW=auto` 旧流程仍可回退。
- 修改飞书卡片表单后，必须确认聊天上传图片、卡片输入手续费/中介费、点击“识别并计算”、输出结果这条链路仍可用。

## 保护检查

```powershell
cd "D:\AIProject\feishuORC\source"
.\check_project_protection.bat
```

通过标准：公式测试、飞书解析测试、边界测试、项目保护测试全部 OK。
