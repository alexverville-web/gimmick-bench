// Times opening the benchmark project. The first open after launch is the
// cold open; the following ones reuse After Effects' in-memory caches.

(function () {
    var job = gbParse(gbReadText(GB_JOB_PATH));
    var payload = { ok: false, opens_s: [] };
    try {
        app.beginSuppressDialogs();
        gbProjectClose();
        var f = new File(job.project_path);
        for (var i = 0; i < job.opens; i++) {
            $.hiresTimer; // reading resets the timer
            app.open(f);
            var us = $.hiresTimer;
            payload.opens_s.push(us / 1e6);
            gbProjectClose();
        }
        app.endSuppressDialogs(false);
        payload.ae_version = app.version;
        payload.ok = true;
    } catch (e) {
        payload.error = e.toString();
    }
    gbFinish(job, payload);
    if (job.quit) { gbQuit(); }
})();
