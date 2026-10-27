"""Copy the benchmark's scripts and footage into ~/GimmickBench before the apps use them.

On macOS, After Effects and Cinema 4D need their own permission to read the Desktop,
Documents and Downloads folders, which is where the benchmark folder usually is. Their
copies under the home folder can be read without any prompt."""
import hashlib
import shutil
from pathlib import Path

from ..config import home_dir


def _digest(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            st = p.stat()
            h.update(f"{p.relative_to(folder)}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()


def staged(src: Path, name: str) -> Path:
    """A copy of src under ~/GimmickBench/bundle/<name>, refreshed when src changes."""
    dest = home_dir() / "bundle" / name
    stamp = dest / ".source-digest"
    digest = _digest(src)
    if stamp.exists() and stamp.read_text() == digest:
        return dest
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)
    stamp.write_text(digest)
    return dest
