# 废纸 ORC 飞书部署

飞书便携版默认采用云端 `PP-OCRv5` 优先、本地 `PP-OCRv5 mobile` 自动回退。云端 Token 可暂时留空，后期只需填写运行目录 `app\.env` 并重启托盘，无需重新构建。

这是从废纸 ORC 图片计算器复制出来的独立项目，专门用于飞书原生长连接机器人部署。当前本机主项目在 `D:\AIProject\feishuORC`：`source` 是后续修改源码，`app` 是可直接运行的便携版。格式化或拔掉 E 盘不会影响 D 盘项目运行。

## 飞书机器人启动

安装飞书 SDK：

```powershell
cd D:\AIProject\feishuORC\source
setup_feishu_env.bat
```

复制 `.env.example` 为 `.env`，填入飞书自建应用的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。

检查配置：

```powershell
python -m feishu_bot.main --check-config
```

启动机器人：

```powershell
run_feishu_bot.bat
```

指定 OCR 模式启动：

```powershell
run_feishu_bot_local.bat
run_feishu_bot_cloud.bat
```

后台托盘版：

```powershell
.\run_feishu_bot_tray_local.bat
.\run_feishu_bot_tray_cloud.bat
```

托盘版启动后会显示一个状态窗口。点窗口右上角 X 只会隐藏窗口，机器人继续后台运行；真正退出请右键托盘图标选择“退出”。

`local` 使用本机 `.venv-ocr`，图片不上传云端；`cloud` 会把图片提交到配置的 PaddleOCR 云端 API。

识别结果默认用飞书消息卡片回复；如果想临时切回纯文本，把 `.env` 里的 `ORC_FEISHU_REPLY_STYLE` 改为 `text`。

完整飞书后台配置步骤见 `docs/feishu_native_setup.md`。

## Windows 便携安装包

生成可复制到其它 Windows 10/11 电脑运行的完整便携 ZIP：

```powershell
.\build_portable_package.bat
```

产物路径是 `dist/orc-feishu-portable.zip`。把这个 ZIP 复制到其它电脑后，解压并先运行 `configure-first-run.bat` 填写飞书密钥和 OCR 配置，再运行：

- `start-feishu-tray.bat`：飞书机器人托盘版，推荐日常运行。
- `start-feishu-bot.bat`：飞书机器人控制台版，适合查看实时输出。
- `start-local.bat`：本地网页/API。
- `check-runtime.bat`：检查飞书配置、本地 OCR 和云 OCR。

便携包不会打包当前 `.env`，也不会传播当前机器的飞书或云 OCR 密钥。

## 本地启动

```powershell
cd D:\AIProject\feishuORC\source
python orc-calc.py serve --host 127.0.0.1 --port 8765 --open
```

也可以双击 `run_local.bat`。页面默认地址是 `http://127.0.0.1:8765`。

## 命令行调用

```powershell
python orc-calc.py recognize "jianhui 模板.jpg" --ocr local --json
python orc-calc.py recognize "jingzhou 模板.jpg" --ocr cloud --json
```

飞书机器人默认通过上面的 CLI 调用本项目内 ORC，不反向引用旧项目路径。

## HTTP API

- `GET /api/v1/health`
- `GET /api/v1/templates`
- `POST /api/v1/recognize`
- `POST /api/v1/calculate`
- `GET /api/v1/docs`

`POST /api/v1/recognize` 示例：

```json
{
  "ocr": "local",
  "template_id": "auto",
  "filename": "jianhui 模板.jpg",
  "image_base64": "..."
}
```

## 计算公式

- `司磅重量 = 毛重 - 皮重`
- `客户手续费 = 司磅重量 * 手续费`
- `客户中介费 = 司磅重量 * 中介费`
- `收厂钱 = 单价 * 结算重量 - 税费`
- `转客户钱 = 收厂钱 - 客户手续费`

中介费继续保留和显示，但不再从“转客户钱”里扣除。

## 回归保护

旧 ORC 已确认过的计算口径已经写入新项目测试，尤其是“转客户钱只扣客户手续费，不扣中介费”。修改飞书机器人、消息解析或 OCR 模式后，先运行：

```powershell
.\check_project_protection.bat
```

当前可用状态和保护规则记录在 `docs/project_protection_record.md`。

## OCR 模式

- `local`：本地 PaddleOCR 标准模型，CPU 推理。
- `local-fast` / `fast`：本地 PaddleOCR mobile 快速模型。
- `cloud`：云端 OCR 预留接口，只在选择云端时调用。

本地 OCR 安装：

```powershell
install_ocr_cpu.bat
```

云端 OCR 可通过环境变量接入：

```powershell
setx PADDLEOCR_API_URL "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
setx PADDLEOCR_ACCESS_TOKEN "你的访问令牌"
setx PADDLEOCR_CLOUD_MODEL "PP-OCRv5"
```

也可以把同名变量写进 `.env`。检查本地和云端状态：

```powershell
check_ocr_modes.bat
```

## 保护边界

- `orc_calc/core`：公式、模板、字段归一化，不为飞书适配修改。
- `orc_calc/ocr`：本地或云端 OCR 适配器。
- `feishu_bot`：飞书原生长连接机器人，只通过 CLI 调用 ORC。
- `static`：本地网页界面。
- `runtime/feishu`：飞书下载图片和机器人日志。
