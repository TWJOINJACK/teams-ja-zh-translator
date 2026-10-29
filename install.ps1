# 安裝中日翻譯小工具：安裝套件、複製到固定位置、設定開機自動啟動、立即啟動
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dest = Join-Path $env:LOCALAPPDATA "TeamsTranslator"

$python = (& py -3 -c "import sys; print(sys.executable)").Trim()
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"

Write-Host "安裝 Python 套件..."
# pip 用的是內建憑證，不認得防毒軟體的憑證；匯出 Windows 信任的根憑證給 pip 使用
$bundle = Join-Path $env:TEMP "teamstranslator-roots.pem"
$sb = New-Object Text.StringBuilder
foreach ($store in "Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root") {
    foreach ($cert in Get-ChildItem $store) {
        [void]$sb.AppendLine("-----BEGIN CERTIFICATE-----")
        [void]$sb.AppendLine([Convert]::ToBase64String($cert.RawData, "InsertLineBreaks"))
        [void]$sb.AppendLine("-----END CERTIFICATE-----")
    }
}
[IO.File]::WriteAllText($bundle, $sb.ToString())
& $python -m pip install --quiet --upgrade --cert $bundle -r (Join-Path $src "requirements.txt")
$code = $LASTEXITCODE
Remove-Item $bundle -ErrorAction SilentlyContinue
if ($code -ne 0) { throw "套件安裝失敗" }

New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $src "translator.py") $dest -Force

$startup = [Environment]::GetFolderPath("Startup")
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $startup "中日翻譯.lnk"))
$lnk.TargetPath = $pythonw
$lnk.Arguments = "`"$(Join-Path $dest 'translator.py')`""
$lnk.WorkingDirectory = $dest
$lnk.Save()

Write-Host "啟動中..."
Start-Process $pythonw -ArgumentList "`"$(Join-Path $dest 'translator.py')`"" -WorkingDirectory $dest
Write-Host "完成！第一次啟動會請你貼上 Claude API 金鑰。"
