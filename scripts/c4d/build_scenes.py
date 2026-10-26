"""Builds the Gimmick Bench Cinema 4D scenes from code. Runs inside c4dpy.

The scenes are generated on each machine (instead of shipping .c4d files) so
the same workload exists in every Cinema 4D version from 2024 on. Any object
or parameter that cannot be created in this version is written to the
manifest so the runner can flag the result as "workload differs".

Job (JSON file named by the GB_JOB environment variable):
  {"out_dir": ..., "assets_dir": ..., "done_path": ...}
"""
import json
import math
import os
import sys
import time

import c4d
from c4d import documents

BUILD_VERSION = "1.0.0"
FPS = 25
missing = []
counts = {}


def note(key, n=1):
    counts[key] = counts.get(key, 0) + n


def obj_id(name, fallback):
    return getattr(c4d, name, fallback)


def make(type_name, fallback, name, parent=None, doc=None):
    try:
        op = c4d.BaseObject(obj_id(type_name, fallback))
    except Exception:
        op = None
    if op is None:
        missing.append({"what": type_name, "where": name})
        return None
    op.SetName(name)
    if parent is not None:
        op.InsertUnderLast(parent)
    elif doc is not None:
        doc.InsertObject(op)
    note("objects")
    return op


def setp(op, param_name, value, fallback_id=None):
    if op is None:
        return False
    pid = getattr(c4d, param_name, fallback_id)
    if pid is None:
        missing.append({"what": param_name, "where": op.GetName()})
        return False
    try:
        op[pid] = value
        return True
    except Exception:
        missing.append({"what": "set " + param_name, "where": op.GetName()})
        return False


def key_real(op, param_name, frames_values, fallback_id=None):
    """Keyframe a float parameter."""
    if op is None:
        return
    pid = getattr(c4d, param_name, fallback_id)
    if pid is None:
        missing.append({"what": "key " + param_name, "where": op.GetName()})
        return
    try:
        did = c4d.DescID(c4d.DescLevel(pid, c4d.DTYPE_REAL, 0))
        track = c4d.CTrack(op, did)
        op.InsertTrackSorted(track)
        curve = track.GetCurve()
        for f, v in frames_values:
            k = curve.AddKey(c4d.BaseTime(f, FPS))["key"]
            k.SetValue(curve, v)
        note("tracks")
    except Exception as e:
        missing.append({"what": "key " + param_name, "where": "%s: %s" % (op.GetName(), e)})


def key_vector(op, param_name, axis, frames_values):
    pid = getattr(c4d, param_name)
    comp = {"x": c4d.VECTOR_X, "y": c4d.VECTOR_Y, "z": c4d.VECTOR_Z}[axis]
    try:
        did = c4d.DescID(c4d.DescLevel(pid, c4d.DTYPE_VECTOR, 0), c4d.DescLevel(comp, c4d.DTYPE_REAL, 0))
        track = c4d.CTrack(op, did)
        op.InsertTrackSorted(track)
        curve = track.GetCurve()
        for f, v in frames_values:
            k = curve.AddKey(c4d.BaseTime(f, FPS))["key"]
            k.SetValue(curve, v)
        note("tracks")
    except Exception as e:
        missing.append({"what": "key %s.%s" % (param_name, axis), "where": "%s: %s" % (op.GetName(), e)})


class Rand(object):
    """Deterministic generator, identical on every machine and Python version."""

    def __init__(self, seed):
        self.s = seed

    def next(self):
        self.s = (self.s * 16807) % 2147483647
        return self.s / 2147483647.0

    def range(self, a, b):
        return a + (b - a) * self.next()


def new_doc(frames):
    doc = documents.BaseDocument()
    doc.SetFps(FPS)
    doc.SetMinTime(c4d.BaseTime(0, FPS))
    doc.SetMaxTime(c4d.BaseTime(frames - 1, FPS))
    doc.SetLoopMinTime(c4d.BaseTime(0, FPS))
    doc.SetLoopMaxTime(c4d.BaseTime(frames - 1, FPS))
    return doc


def material(doc, name, color, texture=None):
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    mat.SetName(name)
    mat[c4d.MATERIAL_COLOR_COLOR] = color
    if texture and os.path.exists(texture):
        sh = c4d.BaseShader(c4d.Xbitmap)
        sh[c4d.BITMAPSHADER_FILENAME] = texture
        mat.InsertShader(sh)
        mat[c4d.MATERIAL_COLOR_SHADER] = sh
        note("textures")
    doc.InsertMaterial(mat)
    return mat


def assign(op, mat):
    if op is None:
        return
    tag = op.MakeTag(c4d.Ttexture)
    tag[c4d.TEXTURETAG_MATERIAL] = mat


def save(doc, path):
    ok = documents.SaveDocument(doc, path, c4d.SAVEDOCUMENTFLAGS_NONE, c4d.FORMAT_C4DEXPORT)
    if not ok:
        raise RuntimeError("could not save " + path)
    return {"path": path, "bytes": os.path.getsize(path)}


# ------------------------------------------------------------------ scenes
def build_geometry(out):
    """Subdivision, deformers, booleans and sweeps that rebuild every frame."""
    frames = 120
    doc = new_doc(frames)
    r = Rand(5005)
    for i in range(16):
        sds = make("Osds", 1007455, "SDS_%d" % i, doc=doc)
        setp(sds, "SDSOBJECT_SUBEDITOR_CM", 3)
        setp(sds, "SDSOBJECT_SUBRAY_CM", 3)
        cube = make("Ocube", 5159, "cube_%d" % i, parent=sds)
        setp(cube, "PRIM_CUBE_SUBX", 12)
        setp(cube, "PRIM_CUBE_SUBY", 12)
        setp(cube, "PRIM_CUBE_SUBZ", 12)
        tw = make("Otwist", 5134, "twist_%d" % i, parent=cube)
        key_real(tw, "DEFORMOBJECT_ANGLE", [(0, 0.0), (frames - 1, math.radians(r.range(90, 270)))])
        bend = make("Obend", 5128, "bend_%d" % i, parent=cube)
        key_real(bend, "DEFORMOBJECT_STRENGTH", [(0, 0.0), (frames - 1, math.radians(r.range(60, 180)))])
        sds.SetAbsPos(c4d.Vector((i % 4) * 450 - 675, 0, (i // 4) * 450 - 675))
    for i in range(6):
        boole = make("Oboole", 1010865, "boole_%d" % i, doc=doc)
        a = make("Osphere", 5160, "a", parent=boole)
        setp(a, "PRIM_SPHERE_SUB", 96)
        b = make("Otorus", 5163, "b", parent=boole)
        setp(b, "PRIM_TORUS_SEG", 96)
        if b is not None:
            key_vector(b, "ID_BASEOBJECT_REL_POSITION", "x", [(0, -120.0), (frames - 1, 120.0)])
        boole.SetAbsPos(c4d.Vector(i * 400 - 1000, 600, 0))
    for i in range(8):
        sweep = make("Osweep", 5118, "sweep_%d" % i, doc=doc)
        prof = make("Osplinecircle", 5181, "profile", parent=sweep)
        setp(prof, "PRIM_CIRCLE_RADIUS", 12.0)
        path = make("Osplinehelix", 5185, "path", parent=sweep)
        setp(path, "PRIM_HELIX_SUB", 400)
        key_real(path, "PRIM_HELIX_END", [(0, math.radians(360)), (frames - 1, math.radians(2880))])
        sweep.SetAbsPos(c4d.Vector(i * 260 - 900, -600, 0))
    return save(doc, os.path.join(out, "geometry.c4d")), frames


def build_mograph(out):
    """Nested cloners with effectors, plus a Voronoi fracture."""
    frames = 120
    doc = new_doc(frames)
    formula = make("Oformulaeffector", 1018883, "formula", doc=doc)
    rnd = make("Orandomeffector", 1018643, "random", doc=doc)
    if rnd is not None:
        key_real(rnd, "ID_MG_BASEEFFECTOR_STRENGTH", [(0, 0.0), (frames - 1, 1.0)], 1003)

    grid = make("Omgcloner", 1018544, "grid_cloner", doc=doc)
    setp(grid, "ID_MG_MOTIONGENERATOR_MODE", getattr(c4d, "ID_MG_MOTIONGENERATOR_MODE_GRIDARRAY", 3))
    setp(grid, "MG_GRID_RESOLUTION", c4d.Vector(30, 30, 12))
    setp(grid, "MG_GRID_SIZE", c4d.Vector(3000, 3000, 1200))
    cube = make("Ocube", 5159, "clone", parent=grid)
    setp(cube, "PRIM_CUBE_LEN", c4d.Vector(40, 40, 40))
    setp(cube, "PRIM_CUBE_DOFILLET", True)
    if grid is not None:
        ie = c4d.InExcludeData()
        for eff in (formula, rnd):
            if eff is not None:
                ie.InsertObject(eff, 1)
        setp(grid, "ID_MG_MOTIONGENERATOR_EFFECTORLIST", ie)
        note("clones", 30 * 30 * 12)

    radial = make("Omgcloner", 1018544, "radial_of_linear", doc=doc)
    setp(radial, "ID_MG_MOTIONGENERATOR_MODE", getattr(c4d, "ID_MG_MOTIONGENERATOR_MODE_RADIAL", 2))
    setp(radial, "MG_POLY_COUNT", 48)
    inner = make("Omgcloner", 1018544, "linear", parent=radial)
    setp(inner, "ID_MG_MOTIONGENERATOR_MODE", getattr(c4d, "ID_MG_MOTIONGENERATOR_MODE_LINEAR", 1))
    setp(inner, "MG_LINEAR_COUNT", 40)
    sph = make("Osphere", 5160, "bead", parent=inner)
    setp(sph, "PRIM_SPHERE_SUB", 24)
    if radial is not None:
        ie2 = c4d.InExcludeData()
        if formula is not None:
            ie2.InsertObject(formula, 1)
        setp(radial, "ID_MG_MOTIONGENERATOR_EFFECTORLIST", ie2)
        key_vector(radial, "ID_BASEOBJECT_REL_ROTATION", "x", [(0, 0.0), (frames - 1, math.radians(180))])
        note("clones", 48 * 40)

    frac = make("Ovoronoifracture", 1036557, "fracture", doc=doc)
    big = make("Osphere", 5160, "rock", parent=frac)
    setp(big, "PRIM_SPHERE_RAD", 500.0)
    setp(big, "PRIM_SPHERE_SUB", 64)
    if frac is not None:
        frac.SetAbsPos(c4d.Vector(0, 1800, 0))
        ie3 = c4d.InExcludeData()
        if formula is not None:
            ie3.InsertObject(formula, 1)
        setp(frac, "ID_MG_MOTIONGENERATOR_EFFECTORLIST", ie3)
    return save(doc, os.path.join(out, "mograph.c4d")), frames


def build_anim(out):
    """Rigid-body simulation plus a deformer stack on a dense mesh."""
    frames = 150
    doc = new_doc(frames)
    r = Rand(6006)
    floor = make("Oplane", 5168, "floor", doc=doc)
    setp(floor, "PRIM_PLANE_WIDTH", 8000.0)
    setp(floor, "PRIM_PLANE_HEIGHT", 8000.0)
    body_tag = obj_id("Trigidbody", 180000102)
    if floor is not None:
        try:
            t = floor.MakeTag(body_tag)
            t[c4d.RIGID_BODY_DYNAMIC] = 0  # collider
            note("collider_tags")
        except Exception:
            missing.append({"what": "dynamics collider tag", "where": "floor"})
    for i in range(400):
        c = make("Ocube", 5159, "body_%d" % i, doc=doc)
        setp(c, "PRIM_CUBE_LEN", c4d.Vector(60, 60, 60))
        c.SetAbsPos(c4d.Vector(r.range(-1500, 1500), 300 + i * 25, r.range(-1500, 1500)))
        c.SetAbsRot(c4d.Vector(r.range(0, 6.28), r.range(0, 6.28), 0))
        try:
            t = c.MakeTag(body_tag)
            t[c4d.RIGID_BODY_DYNAMIC] = 1
            note("rigid_bodies")
        except Exception:
            missing.append({"what": "dynamics body tag", "where": c.GetName()})
            break
    mesh = make("Osphere", 5160, "dense", doc=doc)
    setp(mesh, "PRIM_SPHERE_SUB", 400)
    setp(mesh, "PRIM_SPHERE_TYPE", 0)
    if mesh is not None:
        mesh.SetAbsPos(c4d.Vector(0, 800, -2500))
        for name, fb, param in (("Otwist", 5134, "DEFORMOBJECT_ANGLE"), ("Obend", 5128, "DEFORMOBJECT_STRENGTH"),
                                ("Obulge", 5129, "DEFORMOBJECT_STRENGTH")):
            d = make(name, fb, name, parent=mesh)
            key_real(d, param, [(0, 0.0), (frames // 2, 1.2), (frames - 1, 0.0)])
    return save(doc, os.path.join(out, "anim.c4d")), frames


def build_render(out, assets, engine):
    """A lit product-style shot for the Standard renderer and for Octane."""
    frames = 10
    doc = new_doc(frames)
    tex = os.path.join(assets, "still_texture_4k.jpg")
    mandel = os.path.join(assets, "still_mandelbrot_4k.jpg")
    m_floor = material(doc, "floor", c4d.Vector(0.8, 0.8, 0.8), tex)
    m_hero = material(doc, "hero", c4d.Vector(0.9, 0.4, 0.1))
    m_glass = material(doc, "accent", c4d.Vector(0.1, 0.6, 0.9))
    m_sky = material(doc, "sky", c4d.Vector(1, 1, 1), mandel)

    floor = make("Oplane", 5168, "floor", doc=doc)
    setp(floor, "PRIM_PLANE_WIDTH", 6000.0)
    setp(floor, "PRIM_PLANE_HEIGHT", 6000.0)
    assign(floor, m_floor)
    sky = make("Osky", 5105, "sky", doc=doc)
    assign(sky, m_sky)

    knot = make("Otorus", 5163, "hero_torus", doc=doc)
    setp(knot, "PRIM_TORUS_SEG", 128)
    setp(knot, "PRIM_TORUS_CSUB", 64)
    if knot is not None:
        knot.SetAbsPos(c4d.Vector(0, 250, 0))
        key_vector(knot, "ID_BASEOBJECT_REL_ROTATION", "x", [(0, 0.0), (frames - 1, 0.6)])
    assign(knot, m_hero)

    cl = make("Omgcloner", 1018544, "spheres", doc=doc)
    setp(cl, "ID_MG_MOTIONGENERATOR_MODE", getattr(c4d, "ID_MG_MOTIONGENERATOR_MODE_RADIAL", 2))
    setp(cl, "MG_POLY_COUNT", 36)
    setp(cl, "MG_POLY_RADIUS", 900.0)
    s = make("Osphere", 5160, "ball", parent=cl)
    setp(s, "PRIM_SPHERE_RAD", 70.0)
    setp(s, "PRIM_SPHERE_SUB", 48)
    assign(cl, m_glass)
    if cl is not None:
        cl.SetAbsPos(c4d.Vector(0, 70, 0))

    for i, pos in enumerate([c4d.Vector(-900, 1200, -900), c4d.Vector(1100, 900, -500)]):
        lt = make("Olight", 5102, "area_%d" % i, doc=doc)
        setp(lt, "LIGHT_TYPE", getattr(c4d, "LIGHT_TYPE_AREA", 8))
        setp(lt, "LIGHT_SHADOWTYPE", getattr(c4d, "LIGHT_SHADOWTYPE_AREA", 3))
        if lt is not None:
            lt.SetAbsPos(pos)

    cam = make("Ocamera", 5103, "camera", doc=doc)
    if cam is not None:
        cam.SetAbsPos(c4d.Vector(0, 700, -2200))
        cam.SetAbsRot(c4d.Vector(0, -0.28, 0))
        key_vector(cam, "ID_BASEOBJECT_REL_POSITION", "x", [(0, -200.0), (frames - 1, 200.0)])
        bd = doc.GetRenderBaseDraw()
        if bd is not None:
            bd.SetSceneCamera(cam)
        # A Stage object makes the camera the render camera even without a viewport (c4dpy).
        stage = make("Ostage", 5136, "stage", doc=doc)
        setp(stage, "STAGEOBJECT_CLINK", cam)

    rd = doc.GetActiveRenderData()
    rd[c4d.RDATA_XRES] = 1920.0
    rd[c4d.RDATA_YRES] = 1080.0
    rd[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_ALLFRAMES
    rd[c4d.RDATA_SAVEIMAGE] = False
    if engine == "standard":
        rd[c4d.RDATA_RENDERENGINE] = c4d.RDATA_RENDERENGINE_STANDARD
        setp(rd, "RDATA_ANTIALIASING", getattr(c4d, "RDATA_ANTIALIASING_BEST", 2))
        for vp_name, vp_fallback in (("VPambientocclusion", 300001178), ("VPglobalillumination", 1021096)):
            try:
                vp = c4d.documents.BaseVideoPost(obj_id(vp_name, vp_fallback))
                rd.InsertVideoPost(vp)
                note("video_posts")
            except Exception:
                missing.append({"what": vp_name, "where": "render settings"})
        name = "render_standard.c4d"
    else:
        octane_id = 1029525
        try:
            vp = c4d.documents.BaseVideoPost(octane_id)
            rd.InsertVideoPost(vp)
            rd[c4d.RDATA_RENDERENGINE] = octane_id
        except Exception as e:
            raise RuntimeError("Octane render engine not available: %s" % e)
        name = "render_octane.c4d"
    return save(doc, os.path.join(out, name)), frames


def build_heavy(out, assets):
    """Baked high-polygon geometry with textures, for the scene-load test."""
    doc = new_doc(10)
    src = c4d.BaseObject(c4d.Osphere)
    src[c4d.PRIM_SPHERE_SUB] = 220
    src[c4d.PRIM_SPHERE_TYPE] = 0
    doc.InsertObject(src)
    res = c4d.utils.SendModelingCommand(c4d.MCOMMAND_CURRENTSTATETOOBJECT, [src], doc=doc)
    src.Remove()
    if not res:
        raise RuntimeError("could not make the sphere editable")
    poly = res[0]
    per = poly.GetPolygonCount()
    mats = [material(doc, "tex_%d" % i, c4d.Vector(1, 1, 1),
                     os.path.join(assets, n)) for i, n in enumerate(["still_texture_4k.jpg", "still_mandelbrot_4k.jpg"])]
    copies = max(1, int(4000000 / max(per, 1)))
    for i in range(copies):
        c = poly.GetClone()
        c.SetName("baked_%d" % i)
        c.SetAbsPos(c4d.Vector((i % 10) * 250, (i // 10) * 250, 0))
        doc.InsertObject(c)
        assign(c, mats[i % 2])
    note("baked_polygons", per * copies)
    return save(doc, os.path.join(out, "heavy_load.c4d")), 10


def main():
    job = json.load(open(os.environ["GB_JOB"]))
    out, assets = job["out_dir"], job["assets_dir"]
    payload = {"ok": False, "build_version": BUILD_VERSION, "c4d_version": c4d.GetC4DVersion()}
    scenes = {}
    try:
        for key, fn in (("geometry", build_geometry), ("mograph", build_mograph), ("anim", build_anim)):
            info, frames = fn(out)
            info["frames"] = frames
            scenes[key] = info
        info, frames = build_render(out, assets, "standard")
        info["frames"] = frames
        scenes["render_standard"] = info
        info, frames = build_heavy(out, assets)
        scenes["heavy_load"] = info
        if c4d.plugins.FindPlugin(1029525, c4d.PLUGINTYPE_VIDEOPOST) is not None:
            try:
                info, frames = build_render(out, assets, "octane")
                info["frames"] = frames
                scenes["render_octane"] = info
            except Exception as e:
                payload["octane_error"] = str(e)
        payload["octane_available"] = "render_octane" in scenes
        payload["ok"] = True
    except Exception as e:
        import traceback
        payload["error"] = "%s\n%s" % (e, traceback.format_exc())
    payload["scenes"] = scenes
    payload["missing"] = missing
    payload["counts"] = counts
    payload["finished_at"] = time.time()
    with open(job["done_path"], "w") as f:
        json.dump(payload, f, indent=2)


if __name__ == "__main__":
    main()
