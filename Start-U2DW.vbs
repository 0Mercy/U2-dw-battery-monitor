Option Explicit
Dim shell, files, root, script
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
script = files.BuildPath(root, "tray\start.ps1")
shell.Run "powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File """ & script & """", 0, False
