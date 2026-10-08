param([Parameter(Mandatory=$true)][string]$OutDir)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms,System.Drawing,System.Web.Extensions
$root = Split-Path -Parent $PSScriptRoot
# Compile separate files so each file can have its own using directives.
Add-Type -Path @((Join-Path $root 'tray\TrayApp.cs'), (Join-Path $PSScriptRoot 'TrayAcceptance.cs')) -ReferencedAssemblies System.Windows.Forms,System.Drawing,System.Web.Extensions
[U2DWTray.Acceptance]::Run((Get-Command python.exe).Source, $root, $OutDir)
