"""Exportaciones del proyecto: manifiesto JSON estructurado y ZIP completo.

El JSON reúne biblias + guion + escenas + assets + costes (todo conectado). El ZIP empaqueta
la carpeta del proyecto (imágenes, clips, audio, finales) más ese manifiesto.
"""
import json
import zipfile

import db


def build_manifest(pid) -> dict:
    p = db.get_project(pid)
    if not p:
        raise ValueError("proyecto no encontrado")
    scenes = db.get_scenes(pid)
    for s in scenes:
        s["assets"] = db.get_assets(pid, scene_id=s["id"])
    return {
        "project": p,
        "characters": db.get_characters(pid),
        "locations": db.get_entities(pid, "location"),
        "props": db.get_entities(pid, "prop"),
        "voices": db.get_entities(pid, "voice"),
        "scenes": scenes,
        "project_assets": db.get_assets(pid, scene_id=None),
        "costs": db.get_costs(pid),
    }


def export_json(pid):
    out = db.project_dir(pid) / "final" / "project.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_manifest(pid), ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def export_zip(pid):
    export_json(pid)  # asegura el manifiesto dentro del ZIP
    pdir = db.project_dir(pid)
    out = pdir / "final" / f"project_{pid}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in pdir.rglob("*"):
            if f.is_file() and f.resolve() != out.resolve():
                z.write(f, f.relative_to(pdir))
    return out
