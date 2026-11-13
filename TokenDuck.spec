# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / "tokenduck.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "assets" / "tokenduck.ico"), "assets"),
           (str(root / "LICENSE"), "."),
           (str(root / "THIRD_PARTY_NOTICES.md"), "."),
           (str(root / "build" / "release-licenses" / "BUNDLED_LICENSES.txt"), "licenses")],
    hiddenimports=[],
    excludes=["unittest", "doctest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="TokenDuck",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "assets" / "tokenduck.ico"),
    version=str(root / "assets" / "version_info.txt"),
)
