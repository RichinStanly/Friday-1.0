# PyInstaller one-folder, windowed build for Friday 1.0.
# Keeping Qt's runtime DLLs beside the executable avoids Windows DLL
# collisions during one-file extraction and does not expose a Python console.
from PyInstaller.building.datastruct import TOC

a = Analysis(
    ["friday.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest", "torch", "transformers", "tensorflow", "scipy", "pandas", "sklearn", "jupyter", "IPython"],
    noarchive=False,
)

# Do not let unrelated native packages place generic MSVC/UCRT DLLs at the
# bundle root, where they can shadow PySide6's matching Qt runtime copies.
_qt_runtime_names = {
    "msvcp140.dll",
    "vcruntime140.dll",
    "ucrtbase.dll",
    "icuuc.dll",
}
a.binaries = TOC(
    entry for entry in a.binaries
    if not (
        "\\" not in entry[0]
        and (
            entry[0].lower() in _qt_runtime_names
            or (entry[0].lower().startswith("icudt") and entry[0].lower().endswith(".dll"))
        )
    )
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Friday",
    icon="assets/friday_icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Friday",
)
