"""SQLite: proyectos, personajes, escenas, assets y costes.

Cada función abre su propia conexión (thread-safe para los jobs en background).
"""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "truebalance.db"
PROJECTS_DIR = Path(__file__).parent / "projects"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,             -- video | promo | comic
    formats TEXT NOT NULL,          -- JSON: ["9:16","16:9"]
    script TEXT NOT NULL,
    models TEXT NOT NULL,           -- JSON: {task: model_id}
    audio_first INTEGER DEFAULT 0,
    voice TEXT DEFAULT 'Kore',
    status TEXT DEFAULT 'nuevo',    -- nuevo|storyboard|imagenes|audio|video|montaje|listo|error
    status_msg TEXT DEFAULT '',
    busy INTEGER DEFAULT 0,         -- 1 si hay job en marcha
    cost_total REAL DEFAULT 0,
    created REAL
);
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT, description TEXT,
    gender TEXT DEFAULT '',         -- hombre | mujer | ''
    voice TEXT DEFAULT '',          -- voz TTS asignada al personaje
    ref_image TEXT DEFAULT '',      -- path relativo al proyecto
    library INTEGER DEFAULT 0,
    approved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    ord INTEGER NOT NULL,
    visual TEXT, dialogue TEXT, camera TEXT, emotion TEXT,
    speaker TEXT DEFAULT '',        -- quién habla ('narrador' para voz en off)
    duration_s REAL DEFAULT 6,
    transition TEXT DEFAULT 'corte',
    status TEXT DEFAULT 'draft',    -- draft|imagen|aprobada|animada
    approved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    scene_id INTEGER,               -- NULL para assets de proyecto (música, final)
    kind TEXT NOT NULL,             -- keyframe_first|keyframe_last|slide|clip|voice|music|final
    format TEXT DEFAULT '',         -- 9:16 | 16:9 | ''
    path TEXT NOT NULL,
    model TEXT, cost REAL DEFAULT 0,
    gen_n INTEGER DEFAULT 1,
    active INTEGER DEFAULT 1,       -- la última generación válida
    created REAL
);
CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    ts REAL, model TEXT, units TEXT, usd REAL
);
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT, description TEXT,
    type TEXT DEFAULT '',           -- interior | exterior | ...
    ref_image TEXT DEFAULT '',      -- plate principal (path relativo al proyecto)
    ref_images TEXT DEFAULT '[]',   -- JSON: plates por ángulo/encuadre
    library INTEGER DEFAULT 0,
    approved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS props (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT, description TEXT,
    category TEXT DEFAULT 'objeto',  -- objeto|vehiculo|vestuario|accesorio|mascota
    owner_character_id INTEGER,      -- personaje dueño (nullable)
    ref_image TEXT DEFAULT '',
    ref_images TEXT DEFAULT '[]',
    library INTEGER DEFAULT 0,
    approved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT,
    base_voice TEXT DEFAULT 'Kore',  -- voz prebuilt Gemini (config.VOICES)
    instruction TEXT DEFAULT '',     -- tono/ritmo/emoción para el TTS
    sample_path TEXT DEFAULT '',     -- muestra de audio (path relativo)
    library INTEGER DEFAULT 0,
    approved INTEGER DEFAULT 0
);
"""


def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_col(c, table, col, decl):
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        # migraciones para DBs anteriores
        _ensure_col(c, "characters", "gender", "TEXT DEFAULT ''")
        _ensure_col(c, "characters", "voice", "TEXT DEFAULT ''")
        _ensure_col(c, "characters", "ref_images", "TEXT DEFAULT '[]'")  # model sheet multi-vista
        _ensure_col(c, "characters", "voice_id", "INTEGER")             # voz del stock reutilizable
        _ensure_col(c, "scenes", "speaker", "TEXT DEFAULT ''")
        _ensure_col(c, "scenes", "char_ids", "TEXT DEFAULT '[]'")       # personajes presentes (JSON)
        _ensure_col(c, "scenes", "location_id", "INTEGER")              # localización de la escena
        _ensure_col(c, "scenes", "prop_ids", "TEXT DEFAULT '[]'")       # objetos presentes (JSON)
        # un proceso recién arrancado no tiene jobs vivos: liberar 'busy' colgados
        c.execute("UPDATE projects SET busy=0 WHERE busy=1")
    PROJECTS_DIR.mkdir(exist_ok=True)


def create_project(title, mode, formats, script, models, audio_first, voice):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO projects (title,mode,formats,script,models,audio_first,voice,created) VALUES (?,?,?,?,?,?,?,?)",
            (title, mode, json.dumps(formats), script, json.dumps(models), int(audio_first), voice, time.time()),
        )
        pid = cur.lastrowid
    pdir = PROJECTS_DIR / str(pid)
    for sub in ("characters", "locations", "props", "scenes", "audio", "clips", "final"):
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    return pid


def get_project(pid):
    with conn() as c:
        r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not r:
        return None
    p = dict(r)
    p["formats"] = json.loads(p["formats"])
    p["models"] = json.loads(p["models"])
    return p


def list_projects():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT id,title,mode,status,cost_total,created FROM projects ORDER BY id DESC")]


def set_status(pid, status=None, msg=None, busy=None):
    sets, vals = [], []
    if status is not None:
        sets.append("status=?"); vals.append(status)
    if msg is not None:
        sets.append("status_msg=?"); vals.append(msg)
    if busy is not None:
        sets.append("busy=?"); vals.append(int(busy))
    vals.append(pid)
    with conn() as c:
        c.execute(f"UPDATE projects SET {','.join(sets)} WHERE id=?", vals)


def project_dir(pid) -> Path:
    return PROJECTS_DIR / str(pid)


# --- personajes ---

def replace_characters(pid, chars):
    with conn() as c:
        c.execute("DELETE FROM characters WHERE project_id=?", (pid,))
        for ch in chars:
            c.execute(
                "INSERT INTO characters (project_id,name,description,gender) VALUES (?,?,?,?)",
                (pid, ch["name"], ch["description"], ch.get("gender", "")),
            )


def get_characters(pid):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM characters WHERE project_id=? ORDER BY id", (pid,))]


def update_character(cid, **kw):
    sets = ",".join(f"{k}=?" for k in kw)
    with conn() as c:
        c.execute(f"UPDATE characters SET {sets} WHERE id=?", (*kw.values(), cid))


# --- escenas ---

def replace_scenes(pid, scenes):
    with conn() as c:
        c.execute("DELETE FROM scenes WHERE project_id=?", (pid,))
        for i, s in enumerate(scenes):
            c.execute(
                "INSERT INTO scenes (project_id,ord,visual,dialogue,camera,emotion,speaker,duration_s,transition) VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, i, s.get("visual", ""), s.get("dialogue", ""), s.get("camera", ""),
                 s.get("emotion", ""), s.get("speaker", ""), float(s.get("duration_s", 6)), s.get("transition", "corte")),
            )


def get_scenes(pid):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM scenes WHERE project_id=? ORDER BY ord", (pid,))]


def get_scene(sid):
    with conn() as c:
        r = c.execute("SELECT * FROM scenes WHERE id=?", (sid,)).fetchone()
    return dict(r) if r else None


def update_scene(sid, **kw):
    sets = ",".join(f"{k}=?" for k in kw)
    with conn() as c:
        c.execute(f"UPDATE scenes SET {sets} WHERE id=?", (*kw.values(), sid))


# --- assets ---

def add_asset(pid, scene_id, kind, path, model="", cost=0.0, fmt=""):
    with conn() as c:
        # las generaciones previas del mismo tipo/escena/formato dejan de ser activas
        c.execute(
            "UPDATE assets SET active=0 WHERE project_id=? AND kind=? AND format=? AND "
            "(scene_id=? OR (scene_id IS NULL AND ? IS NULL))",
            (pid, kind, fmt, scene_id, scene_id),
        )
        n = c.execute(
            "SELECT COALESCE(MAX(gen_n),0)+1 FROM assets WHERE project_id=? AND kind=? AND format=? AND "
            "(scene_id=? OR (scene_id IS NULL AND ? IS NULL))",
            (pid, kind, fmt, scene_id, scene_id),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO assets (project_id,scene_id,kind,format,path,model,cost,gen_n,created) VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, scene_id, kind, fmt, str(path), model, cost, n, time.time()),
        )


def get_assets(pid, scene_id="ANY", kind=None, active_only=True):
    q = "SELECT * FROM assets WHERE project_id=?"
    vals = [pid]
    if scene_id != "ANY":
        q += " AND (scene_id=? OR (scene_id IS NULL AND ? IS NULL))"
        vals += [scene_id, scene_id]
    if kind:
        q += " AND kind=?"
        vals.append(kind)
    if active_only:
        q += " AND active=1"
    q += " ORDER BY id"
    with conn() as c:
        return [dict(r) for r in c.execute(q, vals)]


# --- costes ---

def add_cost(pid, model, units, usd):
    with conn() as c:
        c.execute("INSERT INTO costs (project_id,ts,model,units,usd) VALUES (?,?,?,?,?)",
                  (pid, time.time(), model, units, usd))
        c.execute("UPDATE projects SET cost_total = cost_total + ? WHERE id=?", (usd, pid))


def get_costs(pid):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM costs WHERE project_id=? ORDER BY id DESC", (pid,))]


# --- biblias genéricas (locations, props, voices) -------------------------------
# Los nombres de tabla/columna vienen SIEMPRE de código nuestro, nunca del usuario.

ENTITY_TABLE = {"location": "locations", "prop": "props", "voice": "voices", "character": "characters"}


def _table(entity: str) -> str:
    t = ENTITY_TABLE.get(entity)
    if not t:
        raise ValueError(f"entidad desconocida: {entity}")
    return t


def add_entity(pid, entity, **cols) -> int:
    t = _table(entity)
    keys = ",".join(cols)
    ph = ",".join("?" for _ in cols)
    sql = f"INSERT INTO {t} (project_id{',' + keys if keys else ''}) VALUES (?{',' + ph if ph else ''})"
    with conn() as c:
        cur = c.execute(sql, (pid, *cols.values()))
        return cur.lastrowid


def get_entities(pid, entity):
    t = _table(entity)
    with conn() as c:
        return [dict(r) for r in c.execute(f"SELECT * FROM {t} WHERE project_id=? ORDER BY id", (pid,))]


def get_entity(entity, eid):
    t = _table(entity)
    with conn() as c:
        r = c.execute(f"SELECT * FROM {t} WHERE id=?", (eid,)).fetchone()
    return dict(r) if r else None


def update_entity(entity, eid, **kw):
    t = _table(entity)
    sets = ",".join(f"{k}=?" for k in kw)
    with conn() as c:
        c.execute(f"UPDATE {t} SET {sets} WHERE id=?", (*kw.values(), eid))


def delete_entity(entity, eid):
    t = _table(entity)
    with conn() as c:
        c.execute(f"DELETE FROM {t} WHERE id=?", (eid,))
