' Inicia o Visao OCR Pro pelo codigo-fonte, sem janela de console.
' (Na versao instalada use o atalho, que chama o VisaoOCRPro.exe.)
' Uso: wscript IniciarVisaoOCRPro.vbs            -> servidor + bandeja + navegador
'      wscript IniciarVisaoOCRPro.vbs servidor   -> sem abrir o navegador (autostart)
' Requisitos: Python no PATH, pip install -r requirements.txt e npm run build.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)
extra = ""
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "servidor" Then extra = " --servidor"
End If
sh.CurrentDirectory = pasta
sh.Run "pythonw.exe """ & pasta & "\app_desktop.py""" & extra, 0, False
