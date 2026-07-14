# run.ps1 — arranca TruebalanceComic (NUNCA imprime el token)
# El servidor renueva el token solo con gcloud; este script solo lo siembra para arrancar más rápido.
$ErrorActionPreference = "Stop"
Write-Host "Obteniendo token inicial de Vertex (out.brainrot@gmail.com)..."
$env:VXTOKEN = (gcloud auth print-access-token --account=out.brainrot@gmail.com)
Write-Host "Listo. Web: http://127.0.0.1:8010  (el token se renueva automáticamente)"
Set-Location $PSScriptRoot
python -m uvicorn app:app --host 127.0.0.1 --port 8010
