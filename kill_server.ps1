Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        if ($cmd -match 'clawbridge') {
            Stop-Process -Id $_.Id -Force
            Write-Host "Killed PID $($_.Id): $cmd"
        }
    } catch {}
}
