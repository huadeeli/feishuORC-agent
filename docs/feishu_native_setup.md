# 飞书原生长连接部署说明

这个项目当前主目录是 `D:\AIProject\feishuORC`，用于飞书原生机器人。`source` 是后续修改源码，`app` 是可直接运行的便携版；本项目不依赖 E 盘旧项目。

## 1. 安装依赖

```powershell
cd D:\AIProject\feishuORC\source
setup_feishu_env.bat
```

如果要使用本地 PaddleOCR，还需要按原 ORC 方式安装本地 OCR：

```powershell
install_ocr_cpu.bat
```

## 2. 配置密钥

复制 `.env.example` 为 `.env`，填写飞书自建应用的：

```text
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

默认识别命令会调用本项目内的 `orc-calc.py`：

```text
ORC_CLI_PATH=orc-calc.py
ORC_OCR_MODE=local
ORC_TEMPLATE_ID=auto
```

检查配置：

```powershell
python -m feishu_bot.main --check-config
```

## 3. 飞书开放平台设置

在飞书开放平台创建企业自建应用：

- 开启机器人能力。
- 事件订阅方式选择“使用长连接接收事件”。
- 订阅事件 `im.message.receive_v1`。
- 如果启用 `ORC_FEISHU_IMAGE_WORKFLOW=form`，还需要配置卡片回调/卡片回传交互事件 `card.action.trigger`，用于接收卡片里的“识别并计算”按钮。未配置时，飞书客户端会提示“该应用尚未配置卡片回调”。
- 权限至少覆盖接收消息、发送机器人消息、获取消息中的图片/文件资源。
- 发布应用，并让企业管理员审批。

长连接模式不需要公网 IP、域名或内网穿透，但运行机器必须能访问公网。

## 4. 启动机器人

```powershell
run_feishu_bot.bat
```

或者：

```powershell
python -m feishu_bot.main
```

启动后，在飞书里给机器人发送废纸结算截图。机器人会先回复“正在识别”，再调用本项目内的 ORC CLI 输出识别和计算结果。

图片消息有两种流程：

```text
ORC_FEISHU_IMAGE_WORKFLOW=auto
```

`auto` 是旧流程，上传图片后立即识别并回复结果。

```text
ORC_FEISHU_IMAGE_WORKFLOW=form
```

`form` 是卡片表单流程：图片仍然从飞书聊天框上传；机器人收到图片后发送费用输入卡片；在卡片里填写手续费/吨和中介费/吨，点击“识别并计算”后再执行 OCR 和计算。程序优先更新同一张卡片为结果卡，更新失败会回退为发送新结果卡或纯文本。

如果卡片只显示按钮、不显示输入框，请确认已经使用最新代码重启机器人；费用输入框必须在飞书表单容器中显示。如果点击按钮时飞书顶部提示“该应用尚未配置卡片回调”，请回到飞书开放平台完成卡片回调配置后再重试。

如果要明确选择 OCR 模式：

```powershell
run_feishu_bot_local.bat
run_feishu_bot_cloud.bat
```

- `local`：使用本机 `.venv-ocr`，图片不上传云端。
- `cloud`：使用 PaddleOCR 云端 API，会把图片提交到云端服务。

状态检查：

```powershell
check_ocr_modes.bat
```

## 5. 运行边界

- 飞书下载的图片保存在 `runtime/feishu/downloads`。
- 飞书卡片表单会话保存在 `runtime/feishu/card_sessions`。
- 飞书机器人日志保存在 `runtime/feishu/logs/feishu_bot.log`。
- 飞书适配层只调用 CLI，不直接导入 `orc_calc/core`、`orc_calc/ocr` 或 `orc_calc/api`。
- 后续改飞书消息格式，优先改 `feishu_bot/message_format.py`。
- 后续接多维表格台账时，新增飞书表格模块，不改 ORC 公式。
