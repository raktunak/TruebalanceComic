# claude-memoria — espejo de la memoria interna de Claude

Esta carpeta es un **espejo versionado** de la memoria que Claude Code usa para este proyecto.
La memoria "viva" (la que Claude carga en cada sesión) está fuera del repo, en:

```
%USERPROFILE%\.claude\projects\c--TruebalanceComic\memory\
```

Ese nombre `c--TruebalanceComic` se deriva de clonar el repo en `C:\TruebalanceComic`. Si lo clonas
en otra ruta, el nombre de esa carpeta cambia y habría que ajustarlo en `sync-memoria.ps1`.

## Contenido
- `MEMORY.md` — índice de memorias (una línea por memoria).
- `cinema-estudio-audiovisual.md` — estado y 8 decisiones de diseño del estudio (rama cinema).
- `vertex-ai-brainrot-walloop.md` — auth, modelos y hallazgos verificados de Vertex AI.
- `veo-filtro-ip-terceros.md` — bloqueos por IP/franquicias en imagen y vídeo.
- `orquestador-inteligente.md` — preferencia personal de cómo trabaja Claude (delegar, coste). *Si compartes
  el repo con terceros y no quieres exponer esta preferencia, bórrala del espejo.*

## Cómo usarlo en otro equipo
1. Clona el repo (idealmente en `C:\TruebalanceComic`) y haz `git pull`.
2. Hidrata la memoria de Claude desde el espejo:
   ```
   .\sync-memoria.ps1 pull
   ```
3. Cuando Claude actualice la memoria durante el trabajo, antes de commitear vuelca los cambios al espejo:
   ```
   .\sync-memoria.ps1 push
   ```
   y commitea la carpeta `claude-memoria/`.
