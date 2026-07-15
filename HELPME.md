# HELPME — ejecutar / probar el estudio en otro ordenador

Web local (FastAPI + Jinja + JS, sin build) que genera audiovisual con IA sobre **Google Vertex AI**.
Corre en `127.0.0.1:8010` (solo local): "otro ordenador" significa **instalarlo y ejecutarlo EN ese
equipo**, no acceder por red al tuyo.

## 1. Requisitos del sistema
- **Python 3.11+** en el PATH.
- **Google Cloud SDK (`gcloud`)** en el PATH.
- **ffmpeg** en el PATH (para el montaje de vídeo). Referencia probada: ffmpeg 8.0.

## 2. Clonar e instalar dependencias
```
git clone https://github.com/raktunak/TruebalanceComic.git
cd TruebalanceComic
git checkout cinema
python -m pip install -r requirements.txt
```

## 3. Autenticación Vertex AI (IMPRESCINDIBLE)
El proyecto GCP es **`brainrot-walloop`** y **solo la cuenta `out.brainrot@gmail.com` tiene acceso**
(otras cuentas emiten token pero devuelven "caller does not have permission"). En el equipo nuevo:
```
gcloud auth login out.brainrot@gmail.com
```
Sin este login la web abre pero **no genera nada** (errores 401/403).
NUNCA imprimas ni compartas el token de acceso.

## 4. Arrancar
**Windows (PowerShell):**
```
.\run.ps1
```
`run.ps1` obtiene el token con gcloud y lanza uvicorn en http://127.0.0.1:8010 ; el servidor lo
auto-renueva (cada ~50 min y ante cualquier 401).

**Linux / macOS (sin run.ps1):**
```
export VXTOKEN=$(gcloud auth print-access-token --account=out.brainrot@gmail.com)
python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

## 5. Notas importantes
- La base de datos `truebalance.db` y la carpeta `projects/` están en `.gitignore`: el equipo nuevo
  **arranca vacío** (proyectos nuevos), no se copian los del equipo original. La DB se crea sola al arrancar.
- Cada generación se cobra al proyecto GCP; el **contador de coste total** es visible en la cabecera de la UI.
- **No disponibles hoy** (ver `pendientes/PENDIENTES.md`): edición por máscara de píxel, clonación de voz,
  lip-sync a audio. La edición de imagen se hace por **instrucción** (Nano Banana conversacional).
- Diseño y decisiones: `PLAN.md`. Guía detallada de conexión a Vertex: `help.txt`.

## 6. Memoria de Claude (opcional)
El repo incluye `claude-memoria/`, un **espejo versionado** de la memoria interna de Claude para este
proyecto (decisiones de diseño, notas de Vertex, etc.). Claude Code la carga desde `~/.claude`, no del
repo, así que tras clonar hidrátala una vez:
```
.\sync-memoria.ps1 pull
```
Y antes de commitear cambios de memoria, vuélcalos al espejo con `.\sync-memoria.ps1 push`.
Detalles en `claude-memoria/README.md`.

## 7. Prueba rápida de que funciona
1. Abre http://127.0.0.1:8010 y crea un proyecto (pega un guion breve).
2. Sección **Personajes → Crear por prompt** (ej. "mujer pelirroja con chaqueta vaquera"): la IA rellena
   la ficha y genera su imagen de referencia.
3. Sección **Localizaciones**: crea una (ej. "cafetería con ventana grande").
4. **Storyboard/Escenas**: enlaza personaje + localización a una escena y pulsa **Generar imágenes**;
   la imagen debe mantener la identidad del personaje en esa localización.
5. En la escena, **Editar por instrucción** (ej. "cambia la chaqueta a roja"): conserva el rostro y cambia solo eso.
