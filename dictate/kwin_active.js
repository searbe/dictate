// Loaded into KWin at runtime by activewin.py (never installed): reports each focused window to Dictate,
// and its title whenever that changes (e.g. a browser switching from a Gmail tab to WhatsApp Web).
var active = null;

function report(w, switched) {
    if (w) callDBus("local.dictate", "/", "local.dictate", "Active", String(w.resourceClass), String(w.caption), w.pid || 0, switched);
}

function retitled() {
    report(workspace.activeWindow, false);
}

function activated(w) {
    if (active) {
        try { active.captionChanged.disconnect(retitled); } catch (e) {}  // the window may be gone
    }
    active = w;
    if (w) w.captionChanged.connect(retitled);
    report(w, true);
}

workspace.windowActivated.connect(activated);
activated(workspace.activeWindow);
