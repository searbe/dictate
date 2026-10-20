// Loaded into KWin at runtime by activewin.py (never installed): reports each focused window to Dictate.
function report(w) {
    if (w) callDBus("local.dictate", "/", "local.dictate", "Active", String(w.resourceClass), String(w.caption), w.pid || 0);
}
workspace.windowActivated.connect(report);
report(workspace.activeWindow);
