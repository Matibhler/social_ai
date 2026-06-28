'' Launches Social AI server silently in the background (no visible window)
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c """ & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\start.bat""", 0, False
