$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = (Resolve-Path (Join-Path $projectRoot ".venv\Scripts\python.exe")).Path

function Start-Backend([string]$role) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $pythonPath
    $info.Arguments = "-m app.backend.cli --role $role"
    $info.WorkingDirectory = $projectRoot
    $info.UseShellExecute = $true
$info.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($info)
}

$customer = Start-Backend "customer"
$customerService = Start-Backend "customer_service"

Write-Host ""
Write-Host "两个服务已启动："
Write-Host "客户端：  http://127.0.0.1:8000/"
Write-Host "客服端：  http://127.0.0.1:8001/workspace/chat"
Write-Host "进程 PID：客户端 $($customer.Id)，客服端 $($customerService.Id)" -ForegroundColor DarkGray
