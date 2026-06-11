Set WshShell = CreateObject("WScript.Shell")
Dim botDir
botDir = "E:\Template-Repo-Main\SkillBot"
WshShell.Run "cmd /c cd /d """ & botDir & """ && venv\Scripts\python.exe bot.py", 0, False