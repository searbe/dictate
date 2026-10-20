# Windows 10/11 (x64). Needs Python 3.14 (GTK's Python bindings are built for it):
#   winget install -e --id Python.Python.3.14
# Everything else goes into this folder: gtk\ (GTK 3 runtime), .venv\ (Python deps), bin\ (llama.cpp)
# and models\. Safe to re-run. Run with:  powershell -ExecutionPolicy Bypass -File setup-windows.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Gvsbuild = "2026.8.0"  # GTK 3 build from https://github.com/wingtk/gvsbuild (includes PyGObject wheels)

$Python = $null
foreach ($cmd in @(@("py", "-3.14"), @("python"))) {  # the py launcher, else a python on PATH
    try {
        $exe = & $cmd[0] $cmd[1..9] -c "import sys; print(sys.executable if sys.version_info[:2] == (3, 14) else '')" 2>$null
        if ($exe) { $Python = $exe.Trim(); break }
    } catch {}
}
if (-not $Python) { throw "Python 3.14 not found. Install it with: winget install -e --id Python.Python.3.14" }

if (-not (Test-Path gtk\bin)) {
    $url = "https://github.com/wingtk/gvsbuild/releases/download/$Gvsbuild/GTK3_Gvsbuild_${Gvsbuild}_x64.zip"
    & $Python -c "from fetch import download, unpack; from pathlib import Path; z = Path('gtk.zip'); download('$url', z); print('Unpacking GTK ...'); unpack(z, Path('gtk')); z.unlink()"
    if ($LASTEXITCODE) { throw "GTK download failed" }
}

if (-not (Test-Path .venv\Scripts\python.exe)) { & $Python -m venv .venv }
$Wheels = (Get-ChildItem gtk\wheels\pycairo-*.whl, gtk\wheels\pygobject-*.whl).FullName
& .venv\Scripts\pip install -q --no-cache-dir --disable-pip-version-check --upgrade @Wheels sherpa-onnx numpy pynput sounddevice
if ($LASTEXITCODE) { throw "pip install failed" }
& .venv\Scripts\python fetch.py
if ($LASTEXITCODE) { throw "model download failed" }

# A shortcut in this folder to start Dictate (use "Run at startup" in its menu to start it at login)
$Shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut("$PSScriptRoot\Dictate.lnk")
$Shortcut.TargetPath = "$PSScriptRoot\.venv\Scripts\pythonw.exe"
$Shortcut.Arguments = "`"$PSScriptRoot\dictate.py`""
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.Save()

Write-Host ""
Write-Host "Done. Double-click Dictate.lnk (or run: .venv\Scripts\python dictate.py)."
Write-Host "Hold Ctrl+Win to dictate. Tick 'Run at startup' in its menu to start it when you log in."
