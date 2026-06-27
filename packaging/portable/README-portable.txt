废纸 ORC 飞书便携包使用说明

1. 解压整个 ZIP 到一台 Windows 10/11 电脑。
2. 第一次运行 configure-first-run.bat，填写飞书自建应用的 FEISHU_APP_ID 和 FEISHU_APP_SECRET。
3. 运行 check-runtime.bat 检查飞书配置、本地 OCR 和云 OCR。
4. 启动飞书机器人：
   - start-feishu-tray.bat：托盘版，推荐日常使用。
   - start-feishu-bot.bat：控制台版，适合看实时日志。
5. 启动本地网页/API：
   - start-local.bat，默认打开 http://127.0.0.1:8765。

注意：
- 便携包不会内置当前电脑的 .env 密钥；首次配置会在 app\.env 写入新配置。
- 本地 OCR 使用 app\ocr-runtime 和 app\ocr_cache，不需要目标电脑预先安装 Python。
- 云 OCR 需要在首次配置时填写 PADDLEOCR_ACCESS_TOKEN，图片会提交到云端 OCR。
- 飞书长连接模式不需要公网 IP、域名或内网穿透，但电脑必须能访问公网。
- 同一个飞书应用建议只在一台电脑上运行机器人，迁移时先关闭旧电脑上的机器人，避免重复回复。
