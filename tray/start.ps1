param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing, System.Web.Extensions
    if (-not $PythonPath) {
        $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source
    }
    $PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $source = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'TrayApp.cs') -Raw -Encoding UTF8
    Add-Type -TypeDefinition $source -ReferencedAssemblies System.Windows.Forms, System.Drawing, System.Web.Extensions
    [U2DWTray.App]::Run($PythonPath, $projectRoot)
}
catch {
    $stateDirectory = Join-Path $env:LOCALAPPDATA 'U2DWTray'
    New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
    $_.ToString() | Set-Content -LiteralPath (Join-Path $stateDirectory 'startup-error.txt') -Encoding UTF8
    [System.Windows.Forms.MessageBox]::Show(
        'U2-DW tray could not start. See %LOCALAPPDATA%\U2DWTray\startup-error.txt',
        'U2-DW Tray') | Out-Null
    exit 1
}
