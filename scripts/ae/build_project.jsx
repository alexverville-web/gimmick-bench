// Builds the Gimmick Bench After Effects project from code.
//
// Run by the benchmark runner through a small wrapper that defines GB_JOB_PATH
// and GB_SCRIPTS_DIR. The project is generated on each machine (instead of
// shipping an .aep) because projects saved in newer After Effects versions do
// not open in older ones, and the studio runs 2025 and later.
//
// Everything is deterministic: same layer counts, same seeds, same settings.
// Anything that fails to build (for example an effect missing in one version)
// is recorded in the manifest instead of silently changing the workload.

var GB_BUILD_VERSION = "1.0.0";
var W = 3840, H = 2160, FPS = 25, DUR = 6;

var gbMissing = [];
var gbCounts = {};

function count(key, n) { gbCounts[key] = (gbCounts[key] || 0) + (n || 1); }

function tryAdd(group, matchName, where) {
    try {
        var p = group.addProperty(matchName);
        if (p) { count("added:" + matchName); return p; }
    } catch (e) {}
    gbMissing.push({ what: matchName, where: where || "" });
    return null;
}

function setp(group, matchName, value) {
    if (!group) { return null; }
    try {
        var p = group.property(matchName);
        p.setValue(value);
        return p;
    } catch (e) {
        gbMissing.push({ what: "set " + matchName, where: group.name || "" });
        return null;
    }
}

function keys(group, matchName, times, values) {
    if (!group) { return null; }
    try {
        var p = group.property(matchName);
        p.setValuesAtTimes(times, values);
        return p;
    } catch (e) {
        gbMissing.push({ what: "keys " + matchName, where: group.name || "" });
        return null;
    }
}

function expr(prop, code, where) {
    if (!prop) { return; }
    try { prop.expression = code; count("expressions"); }
    catch (e) { gbMissing.push({ what: "expression", where: where + ": " + e.toString() }); }
}

function newComp(name, dur) {
    var c = app.project.items.addComp(name, W, H, 1, dur || DUR, FPS);
    c.motionBlur = true;
    c.shutterAngle = 180;
    try { c.displayStartFrame = 0; } catch (e) {}
    return c;
}

// Effect parameters are found by match name first, then by display name in
// English or French (the studio's two UI languages), so the build does not
// depend on the After Effects interface language.
function param(effect, matchName, names) {
    if (!effect) { return null; }
    try { var p = effect.property(matchName); if (p) { return p; } } catch (e) {}
    for (var i = 1; i <= effect.numProperties; i++) {
        var q = effect.property(i);
        for (var n = 0; n < names.length; n++) {
            if (q.name === names[n]) { return q; }
        }
    }
    gbMissing.push({ what: "parameter " + matchName, where: effect.name });
    return null;
}

function animate(prop, times, values, where) {
    if (!prop) { return; }
    try { prop.setValuesAtTimes(times, values); count("keyframed_params"); }
    catch (e) { gbMissing.push({ what: "keys", where: where }); }
}

function fx(layer, matchName) {
    return tryAdd(layer.property("ADBE Effect Parade"), matchName, layer.name);
}

function palette(i) {
    var p = [[0.97, 0.45, 0.09], [0.06, 0.73, 0.51], [0.98, 0.80, 0.08], [0.23, 0.51, 0.96], [0.93, 0.27, 0.47], [0.95, 0.95, 0.95]];
    return p[i % p.length];
}

// ---------------------------------------------------------------- shapes
function addShape(comp, name, kind, size, color, rnd) {
    var l = comp.layers.addShape();
    l.name = name;
    var root = l.property("ADBE Root Vectors Group");
    var grp = tryAdd(root, "ADBE Vector Group", name);
    if (!grp) { return l; }
    var gc = grp.property("ADBE Vectors Group");
    var shape;
    if (kind === 0) {
        shape = tryAdd(gc, "ADBE Vector Shape - Star", name);
        setp(shape, "ADBE Vector Star Points", 5 + (rnd.int(0, 4)));
        setp(shape, "ADBE Vector Star Outer Radius", size);
        setp(shape, "ADBE Vector Star Inner Radius", size * 0.45);
    } else if (kind === 1) {
        shape = tryAdd(gc, "ADBE Vector Shape - Rect", name);
        setp(shape, "ADBE Vector Rect Size", [size * 1.6, size]);
        setp(shape, "ADBE Vector Rect Roundness", size * 0.15);
    } else {
        shape = tryAdd(gc, "ADBE Vector Shape - Ellipse", name);
        setp(shape, "ADBE Vector Ellipse Size", [size * 1.4, size * 1.4]);
    }
    var rough = tryAdd(gc, "ADBE Vector Filter - Roughen", name);
    setp(rough, "ADBE Vector Roughen Size", size * 0.08);
    var trim = tryAdd(gc, "ADBE Vector Filter - Trim", name);
    keys(trim, "ADBE Vector Trim End", [0, DUR * 0.5, DUR], [0, 100, 30]);
    var off = tryAdd(gc, "ADBE Vector Filter - Offset", name);
    keys(off, "ADBE Vector Offset Amount", [0, DUR], [0, size * 0.2]);
    var stroke = tryAdd(gc, "ADBE Vector Graphic - Stroke", name);
    setp(stroke, "ADBE Vector Stroke Color", palette(rnd.int(0, 5)));
    setp(stroke, "ADBE Vector Stroke Width", 6 + rnd.int(0, 10));
    var fill = tryAdd(gc, "ADBE Vector Graphic - Fill", name);
    setp(fill, "ADBE Vector Fill Color", color);
    var rep = tryAdd(gc, "ADBE Vector Filter - Repeater", name);
    if (rep) {
        setp(rep, "ADBE Vector Repeater Copies", 10);
        var rt = rep.property("ADBE Vector Repeater Transform");
        setp(rt, "ADBE Vector Repeater Rotation", 36);
        setp(rt, "ADBE Vector Repeater Scale", [92, 92]);
        setp(rt, "ADBE Vector Repeater Position", [size * 0.3, 0]);
    }
    var gt = grp.property("ADBE Vector Transform Group");
    keys(gt, "ADBE Vector Rotation", [0, DUR], [0, rnd.range(-360, 360)]);
    var t = l.property("ADBE Transform Group");
    var x0 = rnd.range(0, W), y0 = rnd.range(0, H);
    keys(t, "ADBE Position", [0, DUR * 0.5, DUR],
        [[x0, y0], [rnd.range(0, W), rnd.range(0, H)], [x0, y0]]);
    keys(t, "ADBE Scale", [0, DUR], [[60, 60], [130, 130]]);
    l.motionBlur = true;
    count("shape_layers");
    return l;
}

function buildShapes() {
    var rnd = new GbRandom(1001);
    var tile = newComp("PRE_shape_tile");
    for (var i = 0; i < 48; i++) {
        addShape(tile, "tile_" + i, i % 3, rnd.range(60, 160), palette(i), rnd);
    }
    var comp = newComp("BENCH_shapes");
    var bg = comp.layers.addSolid([0.05, 0.05, 0.07], "BG", W, H, 1, DUR);
    for (var k = 0; k < 6; k++) {
        var pl = comp.layers.add(tile);
        pl.motionBlur = true;
        var t = pl.property("ADBE Transform Group");
        keys(t, "ADBE Rotation", [0, DUR], [k * 15, k * 15 + 90]);
        setp(t, "ADBE Scale", [70 + k * 8, 70 + k * 8]);
        pl.startTime = -k * 0.4;
        count("precomp_instances");
    }
    for (var j = 0; j < 24; j++) {
        addShape(comp, "hero_" + j, j % 3, rnd.range(180, 420), palette(j + 2), rnd);
    }
    bg.moveToEnd();
    return comp;
}

// ---------------------------------------------------------------- expressions
function addText(comp, text, size, color) {
    var l = comp.layers.addText(text);
    var tp = l.property("ADBE Text Properties").property("ADBE Text Document");
    var td = tp.value;
    try { td.font = "Arial-BoldMT"; } catch (e) { gbMissing.push({ what: "font Arial-BoldMT", where: text }); }
    td.fontSize = size;
    td.applyFill = true;
    td.fillColor = color;
    td.justification = ParagraphJustification.CENTER_JUSTIFY;
    tp.setValue(td);
    count("text_layers");
    return l;
}

function addTextAnimator(layer, rnd) {
    var anims = layer.property("ADBE Text Properties").property("ADBE Text Animators");
    var a = tryAdd(anims, "ADBE Text Animator", layer.name);
    if (!a) { return; }
    var props = a.property("ADBE Text Animator Properties");
    tryAdd(props, "ADBE Text Position 3D", layer.name);
    tryAdd(props, "ADBE Text Rotation", layer.name);
    tryAdd(props, "ADBE Text Blur", layer.name);
    try {
        props.property("ADBE Text Position 3D").setValue([0, -120, 0]);
        props.property("ADBE Text Rotation").setValue(rnd.range(-40, 40));
        props.property("ADBE Text Blur").setValue([12, 12]);
    } catch (e) { gbMissing.push({ what: "text animator values", where: layer.name }); }
    var sels = a.property("ADBE Text Selectors");
    var range = tryAdd(sels, "ADBE Text Selector", layer.name);
    keys(range, "ADBE Text Percent Offset", [0, DUR], [-100, 100]);
    tryAdd(sels, "ADBE Text Wiggly Selector", layer.name);
}

function buildExpressions() {
    var rnd = new GbRandom(2002);
    var comp = newComp("BENCH_expressions");
    var noise = comp.layers.addSolid([0.5, 0.5, 0.5], "NOISE", W, H, 1, DUR);
    var fn = fx(noise, "ADBE Fractal Noise");
    expr(param(fn, "ADBE Fractal Noise-0023", ["Evolution", "\u00C9volution"]), "time * 120", "NOISE evolution");
    noise.property("ADBE Transform Group").property("ADBE Opacity").setValue(35);

    var ctrl = comp.layers.addNull(DUR);
    ctrl.name = "CTRL";
    var sp = fx(ctrl, "ADBE Slider Control"); if (sp) { sp.name = "Speed"; sp.property(1).setValue(2.2); }
    var am = fx(ctrl, "ADBE Slider Control"); if (am) { am.name = "Amp"; animate(am.property(1), [0, DUR], [40, 160], "amp"); }

    var cols = 16, rows = 10, first = null;
    for (var r = 0; r < rows; r++) {
        for (var c = 0; c < cols; c++) {
            var i = r * cols + c;
            var l = addShape(comp, "dot_" + i, i % 3, 70, palette(i), rnd);
            var t = l.property("ADBE Transform Group");
            // Replace the random path with a grid position the expression animates around.
            var pos = t.property("ADBE Position");
            while (pos.numKeys > 0) { pos.removeKey(1); }
            pos.setValue([(c + 0.5) * W / cols, (r + 0.5) * H / rows]);
            expr(pos,
                "var c = thisComp.layer(\"CTRL\");\n" +
                "var sp = c.effect(\"Speed\")(1); var a = c.effect(\"Amp\")(1);\n" +
                "seedRandom(index, true);\n" +
                "value + [Math.sin(time * sp + index * 0.3), Math.cos(time * sp * 0.7 + index * 0.2)] * a + (wiggle(2, a * 0.3) - value);",
                "dot position");
            var scl = t.property("ADBE Scale");
            while (scl.numKeys > 0) { scl.removeKey(1); }
            expr(scl,
                "var s = thisComp.layer(\"NOISE\").sampleImage(transform.position, [6, 6], true, time);\n" +
                "var l = (s[0] + s[1] + s[2]) / 3; [40 + l * 140, 40 + l * 140];",
                "dot scale");
            var rot = t.property("ADBE Rotation");
            if (c % 8 === 0) {
                rot.setValuesAtTimes([0, 1, 2], [0, 120, 0]);
                expr(rot, "loopOut(\"pingpong\")", "leader rotation");
            } else {
                expr(rot, "thisComp.layer(index - 1).transform.rotation.valueAtTime(time - 0.06) * 0.97", "follower rotation");
            }
            var op = t.property("ADBE Opacity");
            expr(op, "linear(length(transform.position, [" + (W / 2) + "," + (H / 2) + "]), 0, " + (W * 0.6) + ", 100, 25)", "dot opacity");
        }
    }
    for (var k = 0; k < 40; k++) {
        var tl = addText(comp, "GIMMICK", 64 + (k % 5) * 12, palette(k));
        var tt = tl.property("ADBE Transform Group");
        tt.property("ADBE Position").setValue([rnd.range(200, W - 200), rnd.range(150, H - 150)]);
        expr(tl.property("ADBE Text Properties").property("ADBE Text Document"),
            "var n = Math.floor(time * 25 + index * 13);\n\"GIMMICK \" + n + \"  \" + timeToTimecode(time);",
            "source text");
        expr(tt.property("ADBE Rotation"), "wiggle(1.5, 12)", "text rotation");
        addTextAnimator(tl, rnd);
    }
    noise.moveToEnd();
    return comp;
}

// ---------------------------------------------------------------- mixed media
function importFootage(path) {
    var f = new File(path);
    if (!f.exists) { throw new Error("Missing footage " + path); }
    var item = app.project.importFile(new ImportOptions(f));
    count("footage_items");
    return item;
}

function rectMask(layer, x, y, w, h, feather) {
    var masks = layer.property("ADBE Mask Parade");
    var m = tryAdd(masks, "ADBE Mask Atom", layer.name);
    if (!m) { return null; }
    var s = new Shape();
    s.vertices = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
    s.closed = true;
    m.property("ADBE Mask Shape").setValue(s);
    m.property("ADBE Mask Feather").setValue([feather, feather]);
    keys(m, "ADBE Mask Offset", [0, DUR], [0, 60]);
    count("masks");
    return m;
}

function buildLowerThird() {
    var rnd = new GbRandom(3003);
    var c = newComp("PRE_lower_third");
    var bar = addShape(c, "bar", 1, 300, palette(3), rnd);
    var t = addText(c, "GIMMICK STUDIO", 140, [1, 1, 1]);
    t.property("ADBE Transform Group").property("ADBE Position").setValue([W / 2, H * 0.78]);
    addTextAnimator(t, rnd);
    var t2 = addText(c, "Motion design benchmark", 72, [0.9, 0.9, 0.9]);
    t2.property("ADBE Transform Group").property("ADBE Position").setValue([W / 2, H * 0.86]);
    addTextAnimator(t2, rnd);
    return c;
}

function trackMatte(layer, matte) {
    try {
        if (layer.setTrackMatte) { layer.setTrackMatte(matte, TrackMatteType.LUMA); }
        else { matte.moveBefore(layer); layer.trackMatteType = TrackMatteType.LUMA; }
        count("track_mattes");
    } catch (e) { gbMissing.push({ what: "track matte", where: layer.name }); }
}

function buildMixed(job) {
    var rnd = new GbRandom(4004);
    var a = importFootage(job.assets_dir + "/clip_a_4k_h264.mp4");
    var b = importFootage(job.assets_dir + "/clip_b_4k_prores_proxy.mov");
    var still1 = importFootage(job.assets_dir + "/still_mandelbrot_4k.jpg");
    var still2 = importFootage(job.assets_dir + "/still_texture_4k.jpg");
    var lower = buildLowerThird();

    var comp = newComp("BENCH_mixed_4k");
    var base = comp.layers.add(a);
    base.name = "footage A";
    keys(base.property("ADBE Transform Group"), "ADBE Scale", [0, DUR], [[100, 100], [112, 112]]);
    var curves = fx(base, "ADBE CurvesCustom");
    fx(base, "ADBE HUE SATURATION");

    var tex = comp.layers.add(still2);
    tex.blendingMode = BlendingMode.OVERLAY;
    tex.property("ADBE Transform Group").property("ADBE Opacity").setValue(45);

    var inset = comp.layers.add(b);
    inset.name = "footage B inset";
    var it = inset.property("ADBE Transform Group");
    keys(it, "ADBE Position", [0, DUR], [[W * 0.3, H * 0.4], [W * 0.7, H * 0.45]]);
    keys(it, "ADBE Scale", [0, DUR], [[45, 45], [60, 60]]);
    keys(it, "ADBE Rotation", [0, DUR], [-6, 6]);
    inset.motionBlur = true;
    rectMask(inset, 200, 150, W - 400, H - 300, 120);
    fx(inset, "ADBE Drop Shadow");

    var matteSrc = comp.layers.add(still1);
    matteSrc.name = "mandelbrot fill";
    var title = addText(comp, "GIMMICK", 900, [1, 1, 1]);
    title.name = "title matte";
    keys(title.property("ADBE Transform Group"), "ADBE Scale", [0, DUR], [[90, 90], [105, 105]]);
    addTextAnimator(title, rnd);
    title.moveBefore(matteSrc);
    trackMatte(matteSrc, title);

    for (var k = 0; k < 3; k++) {
        var lt = comp.layers.add(lower);
        lt.startTime = k * 0.5;
        lt.motionBlur = true;
        setp(lt.property("ADBE Transform Group"), "ADBE Position", [W / 2, H / 2 - k * 260]);
        count("precomp_instances");
    }
    for (var s = 0; s < 30; s++) {
        addShape(comp, "accent_" + s, s % 3, rnd.range(40, 120), palette(s), rnd);
    }
    var grade = comp.layers.addSolid([1, 1, 1], "GRADE", W, H, 1, DUR);
    grade.adjustmentLayer = true;
    fx(grade, "ADBE CurvesCustom");
    fx(grade, "ADBE Vibrance");
    var grain = fx(grade, "VISINF Grain Implant");
    return comp;
}

// ---------------------------------------------------------------- effects
function buildEffects(job, footageA) {
    var comp = newComp("BENCH_effects");
    var base = comp.layers.add(footageA);
    base.name = "footage A";
    var td = fx(base, "ADBE Turbulent Displace");
    expr(param(td, "ADBE Turbulent Displace-0005", ["Evolution", "\u00C9volution"]), "time * 90", "turbulent evolution");
    fx(base, "ADBE Lumetri");

    var noise = comp.layers.addSolid([0, 0, 0], "fractal", W, H, 1, DUR);
    var fn = fx(noise, "ADBE Fractal Noise");
    expr(param(fn, "ADBE Fractal Noise-0023", ["Evolution", "\u00C9volution"]), "time * 200", "fractal evolution");
    noise.blendingMode = BlendingMode.SCREEN;
    noise.property("ADBE Transform Group").property("ADBE Opacity").setValue(55);

    var glowSrc = comp.layers.add(footageA);
    glowSrc.name = "glow pass";
    glowSrc.blendingMode = BlendingMode.ADD;
    var gb = fx(glowSrc, "ADBE Gaussian Blur 2");
    animate(param(gb, "ADBE Gaussian Blur 2-0001", ["Blurriness", "Flou"]), [0, DUR], [40, 140], "gaussian");
    fx(glowSrc, "ADBE Glo2");
    glowSrc.property("ADBE Transform Group").property("ADBE Opacity").setValue(40);

    var rays = comp.layers.addSolid([1, 1, 1], "LENS", W, H, 1, DUR);
    rays.adjustmentLayer = true;
    var lens = fx(rays, "ADBE Camera Lens Blur");
    animate(param(lens, "ADBE Camera Lens Blur-0001", ["Blur Radius", "Rayon du flou"]), [0, DUR], [0, 30], "lens blur");
    fx(rays, "ADBE Motion Blur");
    fx(rays, "CC Light Rays");

    var fin = comp.layers.addSolid([1, 1, 1], "FINISH", W, H, 1, DUR);
    fin.adjustmentLayer = true;
    fx(fin, "ADBE Lumetri");
    fx(fin, "VISINF Grain Implant");
    return comp;
}

// ---------------------------------------------------------------- render queue
function wrapper(name, inner) {
    var c = newComp(name, inner.duration);
    c.layers.add(inner);
    return c;
}

function pickName(names, patterns) {
    names = names || [];
    for (var p = 0; p < patterns.length; p++) {
        for (var i = 0; i < names.length; i++) {
            if (names[i].indexOf("_HIDDEN") === 0) { continue; }
            if (names[i].toLowerCase().indexOf(patterns[p].toLowerCase()) >= 0) { return names[i]; }
        }
    }
    return null;
}

var RS_PATTERNS = {
    best: ["Best Settings", "optimaux", "Best"],
    draft: ["Draft Settings", "brouillon", "Draft"]
};

function formatOf(om) {
    try { return om.getSettings(GetSettingsFormat.STRING)["Format"]; } catch (e) { return null; }
}

function queue(comp, outDir, kind, rs, manifest) {
    var item = app.project.renderQueue.items.add(comp);
    var used = { comp: comp.name, kind: kind };
    var rsName = pickName(item.templates, RS_PATTERNS[rs]);
    if (rsName) {
        try { item.applyTemplate(rsName); used.render_settings = rsName; } catch (e) { rsName = null; }
    }
    if (!rsName) {
        gbMissing.push({ what: "render settings template (" + rs + ")", where: comp.name });
    }
    var om = item.outputModule(1);
    var ext = "jpg";
    if (kind === "jpeg") {
        try { om.setSettings({ "Format": "JPEG Sequence" }); } catch (e1) {}
        if (String(formatOf(om)).indexOf("JPEG") < 0) {
            var tif = pickName(om.templates, ["TIFF"]);
            if (tif) { om.applyTemplate(tif); ext = "tif"; used.output_module = tif; }
            else { gbMissing.push({ what: "image sequence output", where: comp.name }); }
        }
    } else {
        var patterns = kind === "prores" ? ["ProRes 422 HQ", "ProRes 422", "ProRes", "High Quality", "haute qualit"] : ["H.264"];
        var name = pickName(om.templates, patterns);
        ext = kind === "prores" ? "mov" : "mp4";
        if (name) { om.applyTemplate(name); used.output_module = name; }
        else { gbMissing.push({ what: "output module for " + kind, where: comp.name }); }
    }
    var fname = (kind === "jpeg") ? comp.name + "_[#####]." + ext : comp.name + "." + ext;
    om.file = new File(outDir + "/" + fname);
    used.format_actual = formatOf(om);
    used.output_extension = ext;
    manifest.render_queue.push(used);
    return item;
}

// ---------------------------------------------------------------- main
function gbBuild(job) {
    app.beginSuppressDialogs();
    gbProjectClose();
    app.newProject();
    app.project.bitsPerChannel = 16;

    var manifest = {
        build_version: GB_BUILD_VERSION,
        ae_version: app.version,
        ae_build: app.buildName,
        bits_per_channel: 16,
        comps: {},
        render_queue: [],
        missing: gbMissing,
        counts: gbCounts
    };

    var shapes = buildShapes();
    var expressions = buildExpressions();
    var mixed = buildMixed(job);
    var footageA = null;
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FootageItem && it.name.indexOf("clip_a_4k") === 0) { footageA = it; }
    }
    var effects = buildEffects(job, footageA);
    var preview = wrapper("BENCH_preview", effects);
    var prores = wrapper("BENCH_export_prores", mixed);
    var h264 = wrapper("BENCH_export_h264", mixed);

    var out = job.render_dir;
    queue(shapes, out, "jpeg", "best", manifest);
    queue(expressions, out, "jpeg", "best", manifest);
    queue(mixed, out, "jpeg", "best", manifest);
    queue(effects, out, "jpeg", "best", manifest);
    queue(preview, out, "jpeg", "draft", manifest);
    queue(prores, out, "prores", "best", manifest);
    queue(h264, out, "h264", "best", manifest);

    for (var j = 1; j <= app.project.numItems; j++) {
        var c = app.project.item(j);
        if (c instanceof CompItem) {
            manifest.comps[c.name] = { layers: c.numLayers, frames: Math.round(c.duration * c.frameRate), width: c.width, height: c.height };
        }
    }

    // Surface expressions that failed to evaluate, so a broken build is never benchmarked silently.
    manifest.expression_errors = gbExpressionErrors(expressions, 0.5);

    app.project.save(new File(job.project_path));
    app.endSuppressDialogs(false);
    return manifest;
}

function gbExpressionErrors(comp, t) {
    var errors = [];
    function walk(group, path) {
        for (var i = 1; i <= group.numProperties; i++) {
            var p = group.property(i);
            if (p.propertyType === PropertyType.PROPERTY) {
                if (p.canSetExpression && p.expressionEnabled === false && p.expression !== "") {
                    errors.push(path + "/" + p.name + ": disabled");
                } else if (p.expression !== "" && p.expressionError) {
                    errors.push(path + "/" + p.name + ": " + p.expressionError);
                }
            } else {
                walk(p, path + "/" + p.name);
            }
            if (errors.length > 20) { return; }
        }
    }
    comp.time = t;
    for (var l = 1; l <= comp.numLayers && errors.length <= 20; l++) {
        var layer = comp.layer(l);
        try { layer.property("ADBE Transform Group").property("ADBE Position").valueAtTime(t, false); } catch (e) {}
        walk(layer, layer.name);
    }
    return errors;
}

(function () {
    var job = gbParse(gbReadText(GB_JOB_PATH));
    var payload = { ok: false };
    try {
        payload.manifest = gbBuild(job);
        payload.ok = true;
    } catch (e) {
        payload.error = e.toString() + (e.line ? " (line " + e.line + ")" : "");
        payload.missing = gbMissing;
    }
    gbFinish(job, payload);
    if (job.quit) { app.quit(); }
})();
