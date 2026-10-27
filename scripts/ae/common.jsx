// Shared helpers for Gimmick Bench ExtendScript files (ES3: no JSON object, no let/const).

function gbReadText(path) {
    var f = new File(path);
    f.encoding = "UTF-8";
    if (!f.open("r")) { throw new Error("Cannot read " + path); }
    var s = f.read();
    f.close();
    return s;
}

function gbWriteText(path, text) {
    var f = new File(path);
    f.encoding = "UTF-8";
    if (!f.open("w")) {
        throw new Error("Cannot write " + path +
            ". Enable Preferences > Scripting & Expressions > Allow Scripts to Write Files and Access Network.");
    }
    f.write(text);
    f.close();
}

// The job file is written by our own runner, so eval is acceptable here.
function gbParse(text) { return eval("(" + text + ")"); }

function gbQuote(s) {
    s = String(s);
    var out = "\"";
    for (var i = 0; i < s.length; i++) {
        var c = s.charAt(i), code = s.charCodeAt(i);
        if (c === "\"") { out += "\\\""; }
        else if (c === "\\") { out += "\\\\"; }
        else if (c === "\n") { out += "\\n"; }
        else if (c === "\r") { out += "\\r"; }
        else if (c === "\t") { out += "\\t"; }
        else if (code < 32) { out += "\\u" + ("0000" + code.toString(16)).slice(-4); }
        else { out += c; }
    }
    return out + "\"";
}

function gbStringify(v) {
    if (v === null || v === undefined) { return "null"; }
    var t = typeof v;
    if (t === "number") { return isFinite(v) ? String(v) : "null"; }
    if (t === "boolean") { return v ? "true" : "false"; }
    if (t === "string") { return gbQuote(v); }
    if (v instanceof Array) {
        var parts = [];
        for (var i = 0; i < v.length; i++) { parts.push(gbStringify(v[i])); }
        return "[" + parts.join(",") + "]";
    }
    var items = [];
    for (var k in v) {
        if (v.hasOwnProperty(k)) { items.push(gbQuote(k) + ":" + gbStringify(v[k])); }
    }
    return "{" + items.join(",") + "}";
}

// Deterministic pseudo-random numbers so every machine builds the same project.
function GbRandom(seed) { this.state = seed % 2147483647; if (this.state <= 0) { this.state += 2147483646; } }
GbRandom.prototype.next = function () { this.state = (this.state * 16807) % 2147483647; return (this.state - 1) / 2147483646; };
GbRandom.prototype.range = function (a, b) { return a + (b - a) * this.next(); };
GbRandom.prototype.int = function (a, b) { return Math.floor(this.range(a, b + 1)); };

function gbFinish(job, payload) {
    payload.finished_at = (new Date()).getTime();
    gbWriteText(job.done_path, gbStringify(payload));
}

// Quit without the "save changes?" dialog, which would leave the benchmark waiting.
function gbQuit() {
    gbProjectClose();
    app.quit();
}

function gbProjectClose() {
    if (app.project) {
        try { app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES); } catch (e) {}
    }
}
