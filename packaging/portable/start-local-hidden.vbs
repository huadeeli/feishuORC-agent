Option Explicit
Dim shell, fso, root, ps1, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = fso.BuildPath(root, "start-local-tray.ps1")
If Not fso.FileExists(ps1) Then
  MsgBox "Missing " & ps1, vbCritical, "Waste Paper OCR"
  WScript.Quit 1
End If
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & ps1 & Chr(34)
shell.Run command, 0, False
