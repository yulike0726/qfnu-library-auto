' Launch one QFNU library daily daemon in its own hidden console so it does
' not die when the parent harness/session console closes.
' Usage: wscript.exe qfnu_daemon.vbs [profile]
' The python interpreter comes from %QFNU_PYTHON% (falls back to PATH "python"),
' so no local machine path is baked into the repository.
Option Explicit
Dim fso, sh, root, py, prof, profileArg, relLog, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
py = sh.ExpandEnvironmentStrings("%QFNU_PYTHON%")
If py = "%QFNU_PYTHON%" Then py = "python"

prof = ""
If WScript.Arguments.Count > 0 Then prof = Trim(WScript.Arguments(0))

If prof = "" Then
    profileArg = ""
    relLog = "logs\task.log"
Else
    profileArg = " --profile " & prof
    relLog = "logs\task-" & prof & ".log"
End If

cmd = "cmd.exe /c " & py & " -m qfnu_lib.cli daily" & profileArg & " >> " & relLog & " 2>&1"
sh.CurrentDirectory = root
sh.Run cmd, 0, False