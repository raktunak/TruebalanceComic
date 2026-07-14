"""Montaje final: ffmpeg (vídeo) y Pillow (cómic/promo: PNG+texto, ZIP, PDF)."""
import shutil
import subprocess
import textwrap
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import db

SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
FONT = r"C:\Windows\Fonts\arialbd.ttf"


def _run(args: list, what: str):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg {what} falló: {(r.stderr or '')[-600:]}")


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _ff_sub_path(p: Path) -> str:
    # escape para filtro subtitles en Windows: C\:/ruta/subs.srt
    return str(p).replace("\\", "/").replace(":", "\\:")


def _srt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    ms = int((s - int(s)) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def build_srt(scenes_with_dur, out: Path):
    """scenes_with_dur: [(scene_dict, dur_real_s)]"""
    lines, t, idx = [], 0.0, 1
    for scene, dur in scenes_with_dur:
        if scene["dialogue"]:
            lines.append(f"{idx}\n{_srt_time(t + 0.1)} --> {_srt_time(t + dur - 0.1)}\n{scene['dialogue']}\n")
            idx += 1
        t += dur
    out.write_text("\n".join(lines), encoding="utf-8")
    return idx > 1


def _has_audio(path: Path) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def _scene_av(pid, scene, fmt, tmp: Path, i: int):
    """Construye un mp4 UNIFORME por escena: vídeo normalizado + su audio (voz > nativo >
    silencio) en una única pista AAC, exactamente de la duración del clip. Devuelve (path, dur).
    Al ser todos idénticos en códec/tamaño/fps, se pueden concatenar con -c copy sin desincronía."""
    w, h = SIZES[fmt]
    clips = [a for a in db.get_assets(pid, scene_id=scene["id"], kind="clip") if a["format"] in (fmt, "")]
    if not clips:
        return None, 0.0
    src = Path(clips[-1]["path"])

    nv = tmp / f"v_{i:02d}.mp4"
    _run(["ffmpeg", "-y", "-i", str(src), "-an",
          "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                 f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps=24,format=yuv420p",
          "-c:v", "libx264", "-preset", "fast", "-crf", "19", str(nv)], f"norm vídeo {i}")
    dur = _probe_duration(nv)

    aseg = tmp / f"a_{i:02d}.wav"
    va = db.get_assets(pid, scene_id=scene["id"], kind="voice")
    voice = Path(va[-1]["path"]) if va else None
    if voice and voice.exists():
        _run(["ffmpeg", "-y", "-i", str(voice), "-vn", "-af", f"aresample=48000,apad,atrim=0:{dur:.3f}",
              "-ac", "2", "-c:a", "pcm_s16le", str(aseg)], f"audio voz {i}")
    elif _has_audio(src):  # escena sin locución pero con audio nativo de Veo (ambiente/SFX)
        _run(["ffmpeg", "-y", "-i", str(src), "-vn", "-af", f"aresample=48000,apad,atrim=0:{dur:.3f}",
              "-ac", "2", "-c:a", "pcm_s16le", str(aseg)], f"audio nativo {i}")
    else:
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{dur:.3f}",
              "-ac", "2", "-c:a", "pcm_s16le", str(aseg)], f"silencio {i}")

    av = tmp / f"av_{i:02d}.mp4"
    _run(["ffmpeg", "-y", "-i", str(nv), "-i", str(aseg), "-map", "0:v", "-map", "1:a",
          "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-c:a", "aac", "-ar", "48000", "-ac", "2",
          "-shortest", str(av)], f"mux escena {i}")
    return av, dur


def mux_scene_preview(pid, scene, fmt) -> str:
    """Genera el preview audiovisual de UNA escena (vídeo con su voz ya incrustada) para la
    galería. Es exactamente el mismo clip que se usa en el montaje final."""
    pdir = db.project_dir(pid)
    tmp = pdir / "final" / "tmp_prev"
    tmp.mkdir(parents=True, exist_ok=True)
    av, dur = _scene_av(pid, scene, fmt, tmp, scene["ord"])
    if not av:
        return ""
    out = pdir / "previews" / f"{scene['ord']:02d}_{fmt.replace(':', 'x')}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(av, out)
    db.add_asset(pid, scene["id"], "preview", out, model="ffmpeg", cost=0, fmt=fmt)
    return str(out.relative_to(pdir))


def assemble_video(pid, fmt, burn_subs=True) -> str:
    """Monta el vídeo final concatenando el clip AUDIOVISUAL de cada escena (vídeo + su voz
    ya incrustada, los mismos previews de la galería) y superponiendo música y subtítulos.
    Como todos los clips por escena son uniformes (misma pista AAC, tamaño y fps), el concat
    no puede desincronizar. → final/master_<fmt>.mp4"""
    pdir = db.project_dir(pid)
    tmp = pdir / "final" / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)  # sin restos de montajes anteriores
    tmp.mkdir(parents=True, exist_ok=True)

    scenes = [s for s in db.get_scenes(pid)
              if [a for a in db.get_assets(pid, scene_id=s["id"], kind="clip") if a["format"] in (fmt, "")]]
    if not scenes:
        raise RuntimeError("no hay clips para montar")

    # 1) clip audiovisual uniforme por escena (vídeo + su audio en una única pista)
    avs, durs = [], []
    for i, s in enumerate(scenes):
        av, dur = _scene_av(pid, s, fmt, tmp, i)
        avs.append(av)
        durs.append(dur)

    # 2) concat (todos idénticos → -c copy: 1 vídeo + 1 audio AAC, sin desincronía)
    lst = tmp / "concat.txt"
    lst.write_text("\n".join(f"file '{x.as_posix()}'" for x in avs), encoding="utf-8")
    joined = tmp / "joined.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)], "concat AV")
    total = sum(durs)

    # 3) subtítulos con los MISMOS tiempos por escena
    srt = tmp / "subs.srt"
    has_subs = burn_subs and build_srt(list(zip(scenes, durs)), srt)

    # 4) música de fondo (opcional, en bucle y a bajo volumen)
    music = db.get_assets(pid, scene_id=None, kind="music")
    music_path = Path(music[-1]["path"]) if music else None
    if music_path and not music_path.exists():
        music_path = None

    # 5) salida final: el clip unido ya trae la voz; añadimos música mezclada y/o subtítulos
    out = pdir / "final" / f"master_{fmt.replace(':', 'x')}.mp4"
    if not music_path and not has_subs:
        shutil.copy(joined, out)
        db.add_asset(pid, None, "final", out, model="ffmpeg", cost=0, fmt=fmt)
        return str(out.relative_to(pdir))

    inputs = ["-i", str(joined)]
    fparts, amap = [], "0:a"
    if music_path:
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        fparts.append(f"[1:a]volume=0.15,atrim=0:{total:.3f},asetpts=N/SR/TB[mus]")
        fparts.append("[0:a][mus]amix=inputs=2:duration=first:normalize=0[aout]")
        amap = "[aout]"
    vmap = "0:v"
    if has_subs:
        fparts.append(f"[0:v]subtitles='{_ff_sub_path(srt)}':"
                      "force_style='FontName=Arial,FontSize=14,Bold=1,Outline=2,MarginV=50'[vout]")
        vmap = "[vout]"

    args = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fparts),
            "-map", vmap, "-map", amap,
            "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-c:a", "aac", "-ar", "48000", "-shortest", str(out)]
    _run(args, "mux final")

    db.add_asset(pid, None, "final", out, model="ffmpeg", cost=0, fmt=fmt)
    return str(out.relative_to(pdir))


# ---------- exports cómic / promo ----------

def _overlay_text(img_path: Path, text: str, out_path: Path):
    """Banda superior semitransparente con el texto del slide (modo promo)."""
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    size = max(28, w // 18)
    try:
        font = ImageFont.truetype(FONT, size)
    except OSError:
        font = ImageFont.load_default()
    lines = textwrap.wrap(text, width=24) or [""]
    line_h = size + 8
    pad = size
    box_h = pad * 2 + line_h * len(lines)
    d.rectangle([0, 0, w, box_h], fill=(0, 0, 0, 150))
    y = pad
    for ln in lines:
        bbox = d.textbbox((0, 0), ln, font=font)
        d.text(((w - (bbox[2] - bbox[0])) / 2, y), ln, font=font, fill=(255, 255, 255, 255))
        y += line_h
    Image.alpha_composite(img, band).convert("RGB").save(out_path, "PNG")


def export_stills(pid, fmt) -> dict:
    """Cómic/promo → PNGs finales + ZIP + PDF. Devuelve rutas relativas."""
    p = db.get_project(pid)
    pdir = db.project_dir(pid)
    outdir = pdir / "final" / f"slides_{fmt.replace(':', 'x')}"
    outdir.mkdir(parents=True, exist_ok=True)

    pngs = []
    for s in db.get_scenes(pid):
        assets = [a for a in db.get_assets(pid, scene_id=s["id"], kind="slide") if a["format"] in (fmt, "")]
        if not assets:
            continue
        src = Path(assets[-1]["path"])
        dst = outdir / f"{s['ord'] + 1:02d}.png"
        if p["mode"] == "promo" and s["dialogue"]:
            _overlay_text(src, s["dialogue"], dst)
        else:
            dst.write_bytes(src.read_bytes())
        pngs.append(dst)
    if not pngs:
        raise RuntimeError("no hay slides que exportar")

    zpath = pdir / "final" / f"{p['mode']}_{fmt.replace(':', 'x')}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in pngs:
            z.write(f, f.name)

    pdf = pdir / "final" / f"{p['mode']}_{fmt.replace(':', 'x')}.pdf"
    imgs = [Image.open(f).convert("RGB") for f in pngs]
    imgs[0].save(pdf, save_all=True, append_images=imgs[1:])

    for a in (zpath, pdf):
        db.add_asset(pid, None, "final", a, model="export", cost=0, fmt=fmt)
    return {"zip": str(zpath.relative_to(pdir)), "pdf": str(pdf.relative_to(pdir)), "count": len(pngs)}
