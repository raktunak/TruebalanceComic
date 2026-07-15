# sync-memoria.ps1 — espejo entre la memoria interna de Claude y claude-memoria/ del repo.
#
# La memoria "de verdad" que Claude Code carga vive en:
#   $env:USERPROFILE\.claude\projects\c--TruebalanceComic\memory
# (el nombre c--TruebalanceComic sale de clonar el repo en C:\TruebalanceComic).
# La carpeta claude-memoria/ del repo es un ESPEJO versionado. Este script las sincroniza.
#
# Uso:
#   .\sync-memoria.ps1 pull    # repo -> memoria de Claude   (tras clonar/pull en un equipo nuevo)
#   .\sync-memoria.ps1 push    # memoria de Claude -> repo    (antes de commitear cambios de memoria)
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("pull", "push")]
    [string]$dir
)
$ErrorActionPreference = "Stop"
$repo = Join-Path $PSScriptRoot "claude-memoria"
$claude = Join-Path $env:USERPROFILE ".claude\projects\c--TruebalanceComic\memory"
New-Item -ItemType Directory -Force -Path $repo, $claude | Out-Null

if ($dir -eq "pull") { $src = $repo; $dst = $claude } else { $src = $claude; $dst = $repo }

$files = Get-ChildItem -Path $src -Filter *.md -File -ErrorAction SilentlyContinue
if (-not $files) { Write-Host "No hay .md en $src, nada que sincronizar."; return }
Copy-Item -Path (Join-Path $src "*.md") -Destination $dst -Force
Write-Host "Sincronizado ($dir): $src  ->  $dst  ($($files.Count) ficheros)"
