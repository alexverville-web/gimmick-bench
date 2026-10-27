"""Find installed After Effects, Cinema 4D and Octane, on macOS and Windows.

Supported versions (studio decision, 26 Oct 2026): After Effects 2025 (25.x)
and later, Cinema 4D 2024 and later. Older installs are listed but not used.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

MIN_AE_MAJOR = 25
MIN_C4D_YEAR = 2024
IS_MAC = sys.platform == "darwin"


@dataclass
class AEInstall:
    year: str  # "2025", "2026", "(Beta)"
    root: Path
    app: Path  # .app bundle on macOS, AfterFX.exe on Windows
    aerender: Path
    version: Optional[str] = None
    supported: bool = True
    note: Optional[str] = None

    @property
    def major(self) -> Optional[int]:
        m = re.match(r"(\d+)", self.version or "")
        return int(m.group(1)) if m else None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: str(v) if isinstance(v, Path) else v for k, v in d.items()}


@dataclass
class C4DInstall:
    year: str
    root: Path
    app: Path  # Cinema 4D.app or Cinema 4D.exe
    c4dpy: Optional[Path]
    commandline: Optional[Path]
    version: Optional[str] = None
    supported: bool = True
    note: Optional[str] = None
    octane_candidates: List[str] = field(default_factory=list)

    @property
    def year_int(self) -> Optional[int]:
        m = re.match(r"(20\d\d)", self.version or self.year or "")
        return int(m.group(1)) if m else None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: str(v) if isinstance(v, Path) else v for k, v in d.items()}


def _exe(p: Path) -> Path:
    """On macOS, the binary inside an .app bundle; elsewhere the path itself."""
    if IS_MAC and p.suffix == ".app":
        macos = p / "Contents" / "MacOS"
        if macos.is_dir():
            bins = [b for b in macos.iterdir() if b.is_file() and os.access(b, os.X_OK)]
            stem = p.stem
            for b in bins:
                if b.name == stem:
                    return b
            if bins:
                return bins[0]
    return p


def find_after_effects(platform, override: str = "") -> List[AEInstall]:
    found: List[AEInstall] = []
    roots: List[Path] = []
    if override:
        roots.append(Path(override))
    for base in platform.default_app_roots():
        adobe = base if IS_MAC else base / "Adobe"
        if adobe.is_dir():
            roots.extend(sorted(adobe.glob("Adobe After Effects*")))
    seen = set()
    for root in roots:
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        year = root.name.replace("Adobe After Effects", "").strip() or "?"
        if IS_MAC:
            apps = sorted(root.glob("Adobe After Effects*.app"))
            aer = root / "aerender"
            if not apps:
                continue
            app = apps[0]
        else:
            support = root / "Support Files"
            app = support / "AfterFX.exe"
            aer = support / "aerender.exe"
            if not app.exists():
                continue
        inst = AEInstall(year=year, root=root, app=app, aerender=aer)
        inst.version = platform.app_version(app)
        if not aer.exists():
            inst.supported, inst.note = False, "aerender not found"
        elif inst.major is not None and inst.major < MIN_AE_MAJOR:
            inst.supported, inst.note = False, f"older than After Effects 2025 ({MIN_AE_MAJOR}.x)"
        found.append(inst)
    return sorted(found, key=lambda i: (i.supported, i.major or 0, "Beta" not in i.year), reverse=True)


def find_cinema4d(platform, override: str = "") -> List[C4DInstall]:
    found: List[C4DInstall] = []
    roots: List[Path] = []
    if override:
        roots.append(Path(override))
    for base in platform.default_app_roots():
        if base.is_dir():
            roots.extend(sorted(base.glob("Maxon Cinema 4D*")))
    seen = set()
    for root in roots:
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        year = root.name.replace("Maxon Cinema 4D", "").strip() or "?"
        if IS_MAC:
            app, c4dpy, cmd = root / "Cinema 4D.app", root / "c4dpy.app", root / "Commandline.app"
        else:
            app, c4dpy, cmd = root / "Cinema 4D.exe", root / "c4dpy.exe", root / "Commandline.exe"
        if not app.exists():
            continue
        inst = C4DInstall(
            year=year, root=root, app=app,
            c4dpy=c4dpy if c4dpy.exists() else None,
            commandline=cmd if cmd.exists() else None,
        )
        inst.version = platform.app_version(app)
        if inst.c4dpy is None:
            inst.supported, inst.note = False, "c4dpy not found"
        elif inst.year_int is not None and inst.year_int < MIN_C4D_YEAR:
            inst.supported, inst.note = False, f"older than Cinema 4D {MIN_C4D_YEAR}"
        inst.octane_candidates = [str(p) for p in find_octane_plugin_dirs(inst)]
        found.append(inst)
    return sorted(found, key=lambda i: (i.supported, i.year_int or 0), reverse=True)


def c4d_pref_dirs(inst: C4DInstall) -> List[Path]:
    """User preference folders for this C4D version (they carry a hash suffix)."""
    if IS_MAC:
        base = Path.home() / "Library" / "Preferences" / "Maxon"
    else:
        base = Path(os.environ.get("APPDATA", "")) / "Maxon"
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(f"Maxon Cinema 4D {inst.year}*") if p.is_dir())


def find_octane_plugin_dirs(inst: C4DInstall) -> List[Path]:
    """Folders that look like the Octane plugin. The c4dpy probe confirms it loads."""
    dirs = [inst.root / "plugins"] + [p / "plugins" for p in c4d_pref_dirs(inst)]
    for extra in os.environ.get("g_additionalModulePath", "").split(os.pathsep):
        if extra:
            dirs.append(Path(extra))
    hits = []
    for d in dirs:
        if not d.is_dir():
            continue
        for child in d.iterdir():
            if child.is_dir() and "octane" in child.name.lower():
                hits.append(child)
    return hits


def pick(installs, wanted: Optional[str] = None):
    """Newest supported install, or the one whose year/version matches `wanted`."""
    usable = [i for i in installs if i.supported]
    if wanted:
        for i in usable:
            if wanted in (i.year, i.version) or (i.version or "").startswith(wanted):
                return i
        return None
    return usable[0] if usable else None
