#!/usr/bin/env python3
"""Shows that Dictate works entirely on this computer: python scripts/prove_local.py [--live]

1. Seals off a sandbox with no network: a fresh network namespace with only loopback ("this computer"), and
   an empty /run, so not even the system's DNS resolver can be asked to look something up. It checks the
   seal by trying to reach the internet from inside, and checks the checker: a program that tries to go online
   must show up in the recording as flagged, or the run stops.
2. Runs Dictate inside it, with every network call by every process recorded (strace):
   - by default, the real app with the real speech model and the real llama-server + refinement model,
     dictating a sample recording (only the keyboard, microphone and paste are stand-ins; see
     tests/test_local_only.py);
   - with --live, your actual Dictate with your keyboard and microphone: dictate as usual, then choose Quit
     from its menu.
3. Lists every network call and checks each one stayed on this computer.

Linux only. Needs bubblewrap and strace (SteamOS has both; Ubuntu: sudo apt install bubblewrap strace) and the
models from the setup script. Downloading the models in the first place is the only time Dictate goes online.
"""
import os, re, shutil, socket, subprocess, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / ".venv/bin/python")
TRACED = "execve,clone,clone3,fork,vfork,connect,bind,sendto,sendmsg,sendmmsg"


def main():
    live = "--live" in sys.argv
    if "--inside" in sys.argv:
        return inside(live, Path(sys.argv[sys.argv.index("--inside") + 1]))
    for tool in ("bwrap", "strace"):
        if not shutil.which(tool):
            return fail(f"{tool} isn't installed (Ubuntu/Debian: sudo apt install bubblewrap strace).")
    if not Path(PYTHON).exists():
        return fail("Run the setup script first.")
    if live and dictate_running():
        return fail("Dictate is already running: choose Quit from its menu first, so the copy in the sandbox is the only one.")
    work = Path(tempfile.mkdtemp(prefix="dictate-proof-"))
    uid = os.getuid()
    sandbox = ["bwrap", "--unshare-net", "--die-with-parent", "--dev-bind", "/", "/",
               "--tmpfs", "/run"]  # hides every system service socket: DNS resolver, system D-Bus, nscd…
    if live:  # your desktop session's own sockets (display, audio, session D-Bus) — and nothing else in /run
        sandbox += ["--bind", f"/run/user/{uid}", f"/run/user/{uid}"]
    else:
        sandbox += ["--tmpfs", "/tmp", "--perms", "01777", "--dir", "/tmp/.X11-unix",  # for the test desktop's display
                    "--bind", str(work), str(work)]
    try:
        return subprocess.run([*sandbox, PYTHON, __file__, "--inside", str(work), *(["--live"] if live else [])]).returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)


def dictate_running():
    with socket.socket() as s:  # Dictate holds this port (without accepting connections) while it runs
        try:
            s.bind(("127.0.0.1", 47613))
            return False
        except OSError:
            return True


def fail(message):
    print(message, file=sys.stderr)
    return 2


# --- inside the sandbox ---
def inside(live, work):
    print("DICTATE LOCAL-ONLY CHECK\n")
    print("1. The sandbox")
    interfaces = sorted(name for _, name in socket.if_nameindex())  # this sandbox's own (/sys shows the host's)
    print(f"   Network interfaces: {', '.join(interfaces)}" + ("  (loopback only: this computer)" if interfaces == ["lo"] else ""))
    sealed = interfaces == ["lo"]
    for label, attempt in (("Reaching the internet (1.1.1.1, port 443)", lambda: socket.create_connection(("1.1.1.1", 443), 5)),
                           ("Reaching the internet over IPv6 (2606:4700:4700::1111)",
                            lambda: socket.create_connection(("2606:4700:4700::1111", 443), 5)),
                           ("Looking up a name (example.com)", lambda: socket.getaddrinfo("example.com", 443))):
        try:
            attempt()
            print(f"   {label}: POSSIBLE — the sandbox isn't sealed")
            sealed = False
        except OSError as err:
            print(f"   {label}: blocked ({err.strerror or err})")
    if not sealed:
        print("\nThe sandbox can reach the network, so this check would prove nothing. Stopping.")
        return 1

    # checking the checker: a program that tries to go online must be caught, or a clean result means nothing
    control = work / "control"
    control.mkdir()
    subprocess.run([*recorder(control), sys.executable, "-c", LEAKY], capture_output=True)
    caught = analyse(control, "-")[1]
    print(f"   Checking the checker: a test program that tries to go online is caught: "
          f"{'yes' if caught else 'NO'} ({len(caught)} attempts flagged)")
    for attempt, n in Counter(caught).items():
        print(f"      {n} × {attempt}")
    if not caught:
        print("\nThe trace missed a deliberate attempt to go online, so it can't be trusted. Stopping.")
        return 1

    trace = work / "trace"
    trace.mkdir()
    strace = recorder(trace)
    if live:
        print("\n2. Your Dictate is now running in the sandbox, with every network call recorded.\n"
              "   Dictate as you normally would (several times, with and without Alt for a refinement).\n"
              "   When you're done, choose Quit from Dictate's menu.\n")
        kept = Path(os.environ.get("DICTATE_DATA") or ROOT / "data") / "dictations.jsonl"
        before = len(kept.read_text().splitlines()) if kept.exists() else 0
        ran = subprocess.run([*strace, PYTHON, str(ROOT / "dictate.py")], cwd=ROOT)
        dictations = (len(kept.read_text().splitlines()) if kept.exists() else 0) - before
        worked = ran.returncode == 0 and dictations > 0
        print(f"   Dictate exited ({'normally' if ran.returncode == 0 else f'code {ran.returncode}'}) "
              f"after {dictations} dictation{'s' * (dictations != 1)}.")
        if not dictations:
            print("   (Nothing was dictated, so this run shows only what Dictate does while idle.)")
        marker, done = "dictate.py", f"Your Dictate handled {dictations} dictation{'s' * (dictations != 1)} with your own keyboard and microphone"
    else:
        print("\n2. Dictating inside it: real speech model, real llama-server and refinement model")
        ran = subprocess.run([*strace, PYTHON, str(ROOT / "scripts/test.py"), "-q", "-p", "no:warnings",
                              "-p", "no:cacheprovider",
                              "tests/test_local_only.py::test_a_real_dictation_is_transcribed_and_refined_on_this_computer"], cwd=ROOT,
                             capture_output=True, text=True, env={**os.environ, "TMPDIR": str(work)})
        summary = (ran.stdout.strip().splitlines() or ["(no output)"])[-1]
        worked = ran.returncode == 0 and "passed" in summary and "skipped" not in summary
        print(f"   A sample recording was transcribed, cleaned up and refined: {'yes' if worked else 'NO'} ({summary})")
        if not worked:
            print(ran.stdout[-3000:])
        marker, done = "tests/harness/app.py", "Dictate transcribed and refined speech with the real models"
    return report(trace, marker, worked, done)


LEAKY = """import socket
for attempt in (lambda: socket.create_connection(("1.1.1.1", 443), 3), lambda: socket.getaddrinfo("example.com", 80)):
    try:
        attempt()
    except OSError:
        pass
"""


def recorder(folder):
    """strace, recording every network call (and which program made it) of a command and everything it starts."""
    return ["strace", "-f", "-ff", "--seccomp-bpf", "-qq", "-s", "512", "-e", f"trace={TRACED}", "-o", str(folder / "t")]


# --- reading the trace ---
CALL = re.compile(r"^(\w+)\((.*)\)\s+=\s+(.*)$")


def address(args):
    """(family, where) for the socket address in a call's arguments, or None if there isn't one."""
    fam = re.search(r"sa_family=(AF_\w+)", args)
    if not fam:
        return None
    fam = fam.group(1)
    if fam == "AF_UNIX":
        path = re.search(r'sun_path=(@?)"([^"]*)"', args)
        return fam, (path.group(1) + path.group(2)) if path else "(unnamed)"
    if fam == "AF_INET":
        port, host = re.search(r"sin_port=htons\((\d+)\)", args), re.search(r'inet_addr\("([^"]+)"\)', args)
        return fam, (host.group(1) if host else "?", int(port.group(1)) if port else 0)
    if fam == "AF_INET6":
        port, host = re.search(r"sin6_port=htons\((\d+)\)", args), re.search(r'inet_pton\(AF_INET6, "([^"]+)"', args)
        return fam, (host.group(1) if host else "?", int(port.group(1)) if port else 0)
    return fam, ""


def loopback(host):
    return host.startswith("127.") or host in ("::1", "::ffff:127.0.0.1")


def what_socket(path):
    for key, label in (("journal", "system log (journald)"), ("bus", "D-Bus message bus (desktop messages)"),
                       (".X11-unix", "display server (X11)"), ("wayland", "display server (Wayland)"),
                       ("eis-socket", "display server (Wayland)"), ("runtime/dictate-test", "display server (Wayland)"),
                       ("broadway", "display server (Broadway)"),
                       ("pipewire", "audio server (PipeWire)"), ("pulse", "audio server (PulseAudio)"),
                       ("at-spi", "accessibility bus"), ("kwin", "window manager (KWin)")):
        if key in path:
            return label
    return "local socket"


def program_name(prog, argv):
    """e.g. "llama-server", or for Python the script or module it runs: "pytest", "test.py"."""
    if not Path(prog).name.startswith("python"):
        return Path(prog).name
    if "-m" in argv[:-1]:
        return argv[argv.index("-m") + 1]
    if "-c" in argv:
        return "python -c (a one-off program)"
    return next((Path(a).name for a in argv[1:] if not a.startswith("-")), "python")


def analyse(trace, marker):
    """Every recorded network call, grouped by (section, program), and the ones that tried to leave this computer."""
    names, parent, calls = {}, {}, []
    for f in sorted(trace.iterdir()):
        pid = int(f.name.split(".")[-1])
        for line in f.read_text(errors="replace").splitlines():
            m = CALL.match(line)
            if not m:
                continue
            name, args, result = m.groups()
            if name == "execve" and result.startswith("0"):
                prog = re.match(r'"([^"]+)"', args).group(1)
                argv = re.findall(r'"([^"]*)"', args.split("], ")[0])[1:]
                names[pid] = "Dictate" if any(a.endswith(marker) for a in argv) else program_name(prog, argv)
            elif name in ("clone", "clone3", "fork", "vfork") and result.split()[0].isdigit():
                parent[int(result.split()[0])] = pid
            elif name in ("connect", "bind", "sendto", "sendmsg", "sendmmsg"):
                addr = address(args)
                if addr and addr[0] != "AF_UNSPEC":
                    calls.append((pid, name, addr, result))

    def program(pid):
        seen = set()
        while pid not in names and pid in parent and pid not in seen:
            seen.add(pid)
            pid = parent[pid]
        return names.get(pid, "?")

    def in_dictate(pid):  # Dictate itself, or a program it started (llama-server)
        seen = set()
        while pid not in seen:
            seen.add(pid)
            if names.get(pid) == "Dictate":
                return True
            if pid not in parent:
                return False
            pid = parent[pid]
        return False

    own_ports = {addr[1][1]: program(pid) for pid, name, addr, result in calls
                 if name == "bind" and addr[0] in ("AF_INET", "AF_INET6") and loopback(addr[1][0])
                 and addr[1][1] and result.startswith("0")}
    groups, problems = defaultdict(Counter), []
    for pid, name, (fam, where), result in calls:
        who = (0 if program(pid) == "Dictate" else 1 if in_dictate(pid) else 2, program(pid))
        error = result.split(" ", 2)[1] if result.startswith("-1") else None
        outcome = f"  [failed: {error}]" if error and error != "EINPROGRESS" else ""  # EINPROGRESS: connecting
        if fam == "AF_UNIX":
            label = f"{what_socket(where)}: {where}"
        elif fam == "AF_NETLINK":
            label = "the kernel (asking about network settings, not the network)"
        elif fam in ("AF_INET", "AF_INET6") and loopback(where[0]):
            host, port = where
            if name == "bind":
                label = f"opens {host} port {port}" + (" (any free port)" if port == 0 else "") + " on this computer"
            elif port in own_ports:
                label = f"this computer, {host} port {port}: {own_ports[port]}"
            else:
                label = f"this computer, {host} port {port}: NOTHING HERE STARTED THAT (e.g. 53 = a DNS lookup)"
                problems.append(f"{who[1]}: {name} to {host} port {port}, which nothing here opened"
                                + (" (port 53: a DNS lookup)" if port == 53 else "") + outcome)
        else:
            label = f"{fam} {where}: OFF THIS COMPUTER"
            target = f"{where[0]} port {where[1]}" if fam in ("AF_INET", "AF_INET6") else f"{fam} {where}"
            problems.append(f"{who[1]}: {name} to {target}, off this computer{outcome}")
        groups[who][f"{name:8} {label}{outcome}"] += 1
    return groups, problems, len(set(parent) | set(names)), len(calls)


def report(trace, marker, worked, done):
    groups, problems, processes, calls = analyse(trace, marker)
    print(f"\n3. Every network call, by every process ({calls} calls from {processes} processes and threads)")
    headings = ("Dictate itself", "Programs Dictate started",
                "The test desktop (stand-ins for your own desktop session: KWin, D-Bus, portals; not part of Dictate)")
    for section, heading in enumerate(headings):
        members = sorted(who for who in groups if who[0] == section)
        if members:
            print(f"\n   {heading}:")
        for who in members:
            print(f"     {who[1]}:")
            for label, n in sorted(groups[who].items(), key=lambda kv: -kv[1]):
                print(f"       {n:5} × {label}")
    if not groups:
        print("   (none)")

    print()
    if problems:
        print("RESULT: NOT LOCAL-ONLY. These calls tried to leave this computer:")
        for p, n in Counter(problems).items():
            print(f"   {n} × {p}")
        return 1
    if not worked:
        print("RESULT: INCONCLUSIVE — no network call left this computer, but no dictation was completed.")
        return 1
    print(f"RESULT: LOCAL ONLY. {done}, in a sandbox with no network at all,\n"
          "and no process tried to reach anything beyond this computer.\n\n"
          "Notes: loopback (127.0.0.1) is the computer talking to itself: Dictate asking the llama-server it\n"
          "started to refine the text. \"Local socket\" connections never leave the computer; some fail on\n"
          "purpose, because the sandbox hides the system's services (its log, its DNS resolver, the system bus).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
