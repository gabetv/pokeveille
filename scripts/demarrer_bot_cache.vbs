' Lance scripts\demarrer_bot.cmd sans fenetre (utilise par le raccourci du dossier Demarrage de Windows).
Dim dossier
dossier = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run """" & dossier & "\demarrer_bot.cmd""", 0, False
