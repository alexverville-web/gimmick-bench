"""Times one Cinema 4D workload inside c4dpy and writes the result as JSON.

Job (JSON file named by the GB_JOB environment variable):
  mode "probe":  report version and whether Octane is loaded
  mode "load":   load the scene `loads` times; the first load is cold for this process
  mode "eval":   step through frames start..end with ExecutePasses (animation, generators, simulation)
  mode "render": render frames start..end with the scene's render engine via RenderDocument

Times come from time.perf_counter() around the work only, so c4dpy start-up
and licence checks are never included.
"""
import json
import os
import time

import c4d
from c4d import documents

OCTANE_VP = 1029525


def load(path):
    flags = c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS
    doc = documents.LoadDocument(path, flags, None)
    if doc is None:
        raise RuntimeError("could not load " + path)
    return doc


def run_probe(job):
    vp = c4d.plugins.FindPlugin(OCTANE_VP, c4d.PLUGINTYPE_VIDEOPOST)
    return {
        "c4d_version": c4d.GetC4DVersion(),
        "octane_available": vp is not None,
        "octane_name": vp.GetName() if vp is not None else None,
        "threads": c4d.GeGetCurrentThreadCount() if hasattr(c4d, "GeGetCurrentThreadCount") else None,
    }


def run_load(job):
    times = []
    for _ in range(job.get("loads", 3)):
        t0 = time.perf_counter()
        doc = load(job["scene"])
        times.append(time.perf_counter() - t0)
        documents.KillDocument(doc)
    return {"loads_s": times}


def run_eval(job):
    doc = load(job["scene"])
    fps = doc.GetFps()
    start, end = job["start"], job["end"]
    # Frame 0 is evaluated once untimed so the first timed frame is not paying
    # for the initial build of every generator cache.
    doc.SetTime(c4d.BaseTime(start, fps))
    doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_NONE)
    t0 = time.perf_counter()
    for f in range(start + 1, end + 1):
        doc.SetTime(c4d.BaseTime(f, fps))
        doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_NONE)
    seconds = time.perf_counter() - t0
    n = end - start
    return {"seconds": seconds, "frames": n, "fps": n / seconds if seconds else None}


def run_render(job):
    doc = load(job["scene"])
    rd = doc.GetActiveRenderData()
    data = rd.GetDataInstance().GetClone(c4d.COPYFLAGS_NONE)
    xres, yres = int(data[c4d.RDATA_XRES]), int(data[c4d.RDATA_YRES])
    if job.get("resolution"):
        xres, yres = job["resolution"]
        data[c4d.RDATA_XRES], data[c4d.RDATA_YRES] = float(xres), float(yres)
    engine = data[c4d.RDATA_RENDERENGINE]
    bmp = c4d.bitmaps.MultipassBitmap(xres, yres, c4d.COLORMODE_RGB)
    bmp.AddChannel(True, True)
    fps = doc.GetFps()
    frame_times = []
    for f in range(job["start"], job["end"] + 1):
        doc.SetTime(c4d.BaseTime(f, fps))
        doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_NONE)
        t0 = time.perf_counter()
        res = documents.RenderDocument(doc, data, bmp, c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_NODOCUMENTCLONE)
        frame_times.append(time.perf_counter() - t0)
        if res != c4d.RENDERRESULT_OK:
            raise RuntimeError("RenderDocument returned %s on frame %d" % (res, f))
    if job.get("save_last"):
        bmp.Save(job["save_last"], c4d.FILTER_PNG)
    return {"seconds": sum(frame_times), "frame_times_s": frame_times, "engine": engine,
            "resolution": [xres, yres]}


def main():
    job = json.load(open(os.environ["GB_JOB"]))
    payload = {"ok": False, "mode": job["mode"]}
    try:
        fn = {"probe": run_probe, "load": run_load, "eval": run_eval, "render": run_render}[job["mode"]]
        payload.update(fn(job))
        payload["ok"] = True
    except Exception as e:
        import traceback
        payload["error"] = "%s\n%s" % (e, traceback.format_exc())
    with open(job["done_path"], "w") as f:
        json.dump(payload, f)


if __name__ == "__main__":
    main()
