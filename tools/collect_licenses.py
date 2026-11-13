"""Collect license texts from the actual Windows runtime and build environment."""

import importlib.metadata
from pathlib import Path
import sys
import zipfile


def collect(destination):
    base = Path(sys.base_prefix)
    sections = [("Python " + sys.version.split()[0], (base / "LICENSE.txt").read_text(encoding="utf-8"))]
    tcl_texts = []
    for path in sorted((base / "tcl").glob("*/license.terms")):
        tcl_texts.append((str(path.relative_to(base)), path.read_text(encoding="utf-8")))
    # Python 3.14 on Windows can package Tcl/Tk 9 libraries as ZIP files.
    for path in sorted((base / "tcl").glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.lower().endswith("/license.terms"):
                    tcl_texts.append((path.name + "/" + name, archive.read(name).decode("utf-8")))
    if not tcl_texts:
        raise RuntimeError("Cannot locate Tcl/Tk license texts in this Python installation")
    sections.extend(tcl_texts)
    packages = ("pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "packaging",
                "pefile", "pywin32-ctypes", "setuptools")
    for name in packages:
        distribution = importlib.metadata.distribution(name)
        licenses = [p for p in distribution.files or []
                    if Path(str(p)).name.lower().startswith(("license", "copying"))]
        if not licenses:
            raise RuntimeError("Cannot locate license for " + name)
        for path in sorted(licenses):
            sections.append((name + " " + distribution.version + " / " + Path(str(path)).name,
                             Path(distribution.locate_file(path)).read_text(encoding="utf-8", errors="replace")))
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join("=" * 72 + "\n" + title + "\n" + "=" * 72 + "\n\n" + text
                                    for title, text in sections), encoding="utf-8")
    print("Collected %s license texts" % len(sections))


if __name__ == "__main__":
    collect(sys.argv[1])
