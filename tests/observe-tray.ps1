param([Parameter(Mandatory=$true)][string]$OutFile, [int]$Seconds = 1200)
$ErrorActionPreference = 'Stop'
$statePath = Join-Path $env:LOCALAPPDATA 'U2DWTray\status.json'
$until = (Get-Date).AddSeconds($Seconds)
$encoding = New-Object System.Text.UTF8Encoding($false)
$writer = New-Object System.IO.StreamWriter($OutFile, $false, $encoding)
try {
    while ((Get-Date) -lt $until) {
        $record = [ordered]@{ observed_at=(Get-Date).ToString('o'); state=$null; process=$null }
        try {
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $record.state = $state
            $process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
            if ($process) {
                $record.process = @{id=$process.Id; started=$process.StartTime.ToString('o'); cpu_seconds=$process.CPU; working_set=$process.WorkingSet64; private_bytes=$process.PrivateMemorySize64; handles=$process.HandleCount}
            }
        } catch { $record.error = $_.Exception.GetType().Name }
        $writer.WriteLine(($record | ConvertTo-Json -Compress -Depth 6))
        $writer.Flush()
        Start-Sleep -Seconds 2
    }
} finally { $writer.Dispose() }
