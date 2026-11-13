' TokenDuck launcher: prefer the self-contained executable.
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("Wscript.Shell")
sh.CurrentDirectory = appDir
exePath = appDir & "\TokenDuck.exe"
If Not fso.FileExists(exePath) Then exePath = appDir & "\dist\TokenDuck.exe"
If fso.FileExists(exePath) Then
    sh.Run """" & exePath & """", 0, False
Else
    sh.Run "pythonw.exe """ & appDir & "\tokenduck.py""", 0, False
End If
