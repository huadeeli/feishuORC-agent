param(
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root "app"
$ExePath = Join-Path $AppDir "orc-calc.exe"
$RuntimeDir = Join-Path $AppDir "runtime"
$LogDir = Join-Path $AppDir "logs"
$TrayLog = Join-Path $LogDir "local_tray.log"
$ServerJson = Join-Path $RuntimeDir "server.json"
$PortStart = 8765
$PortEnd = 8784

if ($SelfTest) {
    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { throw "Missing $ExePath" }
    Write-Host "Local tray self-test OK."
    exit 0
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

$script:ServiceProcess = $null
$script:ServiceUrl = ""
$script:Exiting = $false
$script:LastStatus = "正在启动..."

function Write-LocalLog([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $TrayLog -Value $line -Encoding UTF8
}

function Read-LogTail([int]$Limit = 5000) {
    try {
        if (-not (Test-Path -LiteralPath $TrayLog -PathType Leaf)) { return "" }
        $text = Get-Content -LiteralPath $TrayLog -Raw -Encoding UTF8
        if ($text.Length -gt $Limit) { return $text.Substring($text.Length - $Limit) }
        return $text
    } catch {
        return "读取日志失败：$($_.Exception.Message)"
    }
}

function Test-OrcService([string]$BaseUrl) {
    try {
        $response = Invoke-WebRequest -Uri "$BaseUrl/api/v1/templates" -UseBasicParsing -TimeoutSec 1
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Find-OrcServiceUrl {
    foreach ($port in $PortStart..$PortEnd) {
        $url = "http://127.0.0.1:$port"
        if (Test-OrcService $url) { return $url }
    }
    return ""
}

function Get-HealthSummary {
    if (-not $script:ServiceUrl) { return "本地服务未启动" }
    try {
        $health = Invoke-RestMethod -Uri "$($script:ServiceUrl)/api/v1/health" -TimeoutSec 4
        $ocr = if ($health.ocr_ready) { "本地 OCR 已就绪" } else { "本地 OCR 未就绪" }
        $mode = if ($health.runtime_mode) { $health.runtime_mode } else { "unknown" }
        return "地址：$($script:ServiceUrl) | $ocr | $mode"
    } catch {
        return "地址：$($script:ServiceUrl) | 健康检查失败：$($_.Exception.Message)"
    }
}

function Start-LocalService {
    $existing = Find-OrcServiceUrl
    if ($existing) {
        $script:ServiceUrl = $existing
        $script:LastStatus = "已连接到正在运行的本地服务"
        Write-LocalLog "found existing local service: $existing"
        return
    }

    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
        throw "Missing $ExePath"
    }

    Write-LocalLog "starting local OCR web service"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ExePath
    $psi.Arguments = "serve --host 127.0.0.1 --port 8765 --open"
    $psi.WorkingDirectory = $AppDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.EnvironmentVariables["ORC_CALC_OCR_CACHE_DIR"] = (Join-Path $AppDir "ocr_cache")
    $psi.EnvironmentVariables["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
    $script:ServiceProcess = [System.Diagnostics.Process]::Start($psi)

    $deadline = (Get-Date).AddSeconds(18)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $found = Find-OrcServiceUrl
        if ($found) {
            $script:ServiceUrl = $found
            $script:LastStatus = "运行中"
            Write-LocalLog "local service ready: $found, pid=$($script:ServiceProcess.Id)"
            return
        }
    }
    $script:LastStatus = "已启动进程，但服务还没有响应"
    Write-LocalLog "local service process started but health endpoint was not ready"
}

function Stop-LocalService {
    Write-LocalLog "stopping local service"
    if ($script:ServiceProcess -and -not $script:ServiceProcess.HasExited) {
        try {
            $script:ServiceProcess.CloseMainWindow() | Out-Null
            Start-Sleep -Milliseconds 800
            if (-not $script:ServiceProcess.HasExited) { $script:ServiceProcess.Kill() }
        } catch {
            Write-LocalLog "failed to stop owned process: $($_.Exception.Message)"
        }
    } elseif (Test-Path -LiteralPath $ServerJson -PathType Leaf) {
        try {
            $state = Get-Content -LiteralPath $ServerJson -Raw -Encoding UTF8 | ConvertFrom-Json
            $pid = [int]$state.pid
            $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($process -and $process.ProcessName -like "orc-calc*") {
                Stop-Process -Id $pid -Force
                Write-LocalLog "stopped server.json process pid=$pid"
            }
        } catch {
            Write-LocalLog "failed to stop server.json process: $($_.Exception.Message)"
        }
    }
    $script:ServiceProcess = $null
    $script:ServiceUrl = ""
    $script:LastStatus = "已停止"
}

function Open-LocalPage {
    if (-not $script:ServiceUrl) { $script:ServiceUrl = Find-OrcServiceUrl }
    if ($script:ServiceUrl) {
        Start-Process $script:ServiceUrl
    } else {
        [System.Windows.Forms.MessageBox]::Show("本地网页服务还没有启动。", "废纸 OCR 本地计算器") | Out-Null
    }
}

function Restart-LocalService {
    $statusLabel.Text = "正在重新启动本地服务..."
    Stop-LocalService
    Start-LocalService
    Update-Status
}

function Hide-ToTray {
    $form.Hide()
    $notify.ShowBalloonTip(1500, "废纸 OCR 本地计算器", "窗口已隐藏，本地网页服务继续后台运行。", [System.Windows.Forms.ToolTipIcon]::Info)
}

function Show-Window {
    $form.Show()
    $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
    $form.Activate()
}

function Exit-App {
    $script:Exiting = $true
    Stop-LocalService
    $notify.Visible = $false
    $notify.Dispose()
    $form.Close()
}

function Update-Status {
    if ($script:Exiting) { return }
    if (-not $script:ServiceUrl) { $script:ServiceUrl = Find-OrcServiceUrl }
    $health = Get-HealthSummary
    $pidText = "-"
    if ($script:ServiceProcess -and -not $script:ServiceProcess.HasExited) { $pidText = [string]$script:ServiceProcess.Id }
    $statusLabel.Text = "状态：$script:LastStatus | PID：$pidText`r`n$health"
    $logBox.Text = Read-LogTail
    $logBox.SelectionStart = $logBox.TextLength
    $logBox.ScrollToCaret()
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "废纸 OCR 本地计算器"
$form.Size = New-Object System.Drawing.Size(560, 360)
$form.StartPosition = "CenterScreen"
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$form.Add_FormClosing({
    if (-not $script:Exiting) {
        $_.Cancel = $true
        Hide-ToTray
    }
})

$title = New-Object System.Windows.Forms.Label
$title.Text = "废纸 OCR 本地计算器"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 13, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(14, 14)
$title.Size = New-Object System.Drawing.Size(500, 28)
$form.Controls.Add($title)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "正在启动..."
$statusLabel.Location = New-Object System.Drawing.Point(16, 50)
$statusLabel.Size = New-Object System.Drawing.Size(510, 44)
$form.Controls.Add($statusLabel)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "点右上角 X 只会隐藏窗口，不会关闭本地服务。真正退出请右键托盘图标选择: 退出服务。"
$hint.Location = New-Object System.Drawing.Point(16, 98)
$hint.Size = New-Object System.Drawing.Size(510, 36)
$form.Controls.Add($hint)

$openButton = New-Object System.Windows.Forms.Button
$openButton.Text = "打开网页"
$openButton.Location = New-Object System.Drawing.Point(16, 138)
$openButton.Size = New-Object System.Drawing.Size(90, 30)
$openButton.Add_Click({ Open-LocalPage })
$form.Controls.Add($openButton)

$restartButton = New-Object System.Windows.Forms.Button
$restartButton.Text = "重新启动服务"
$restartButton.Location = New-Object System.Drawing.Point(116, 138)
$restartButton.Size = New-Object System.Drawing.Size(110, 30)
$restartButton.Add_Click({ Restart-LocalService })
$form.Controls.Add($restartButton)

$hideButton = New-Object System.Windows.Forms.Button
$hideButton.Text = "隐藏到托盘"
$hideButton.Location = New-Object System.Drawing.Point(236, 138)
$hideButton.Size = New-Object System.Drawing.Size(100, 30)
$hideButton.Add_Click({ Hide-ToTray })
$form.Controls.Add($hideButton)

$exitButton = New-Object System.Windows.Forms.Button
$exitButton.Text = "退出服务"
$exitButton.Location = New-Object System.Drawing.Point(346, 138)
$exitButton.Size = New-Object System.Drawing.Size(90, 30)
$exitButton.Add_Click({ Exit-App })
$form.Controls.Add($exitButton)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.Location = New-Object System.Drawing.Point(16, 180)
$logBox.Size = New-Object System.Drawing.Size(510, 130)
$form.Controls.Add($logBox)

$iconBitmap = New-Object System.Drawing.Bitmap 64, 64
$graphics = [System.Drawing.Graphics]::FromImage($iconBitmap)
$graphics.Clear([System.Drawing.Color]::FromArgb(20, 99, 210))
$brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
$font = New-Object System.Drawing.Font("Arial", 18, [System.Drawing.FontStyle]::Bold)
$graphics.DrawString("OCR", $font, $brush, 7, 18)
$graphics.Dispose()
$iconHandle = $iconBitmap.GetHicon()
$trayIcon = [System.Drawing.Icon]::FromHandle($iconHandle)

$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = $trayIcon
$notify.Text = "废纸 OCR 本地计算器"
$notify.Visible = $true
$notify.Add_DoubleClick({ Show-Window })

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$showItem = $menu.Items.Add("显示窗口")
$showItem.Add_Click({ Show-Window })
$openItem = $menu.Items.Add("打开网页")
$openItem.Add_Click({ Open-LocalPage })
$restartItem = $menu.Items.Add("重新启动服务")
$restartItem.Add_Click({ Restart-LocalService })
[void]$menu.Items.Add("-")
$exitItem = $menu.Items.Add("退出服务")
$exitItem.Add_Click({ Exit-App })
$notify.ContextMenuStrip = $menu

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 2500
$timer.Add_Tick({ Update-Status })
$timer.Start()

try {
    Start-LocalService
    Update-Status
} catch {
    Write-LocalLog "startup failed: $($_.Exception.Message)"
    [System.Windows.Forms.MessageBox]::Show("启动失败：$($_.Exception.Message)", "废纸 OCR 本地计算器") | Out-Null
}

[System.Windows.Forms.Application]::Run($form)
