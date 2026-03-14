# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/home/xinnan/mycode/claude_code/vedio_scraper/video_scraper.py'],
    pathex=[],
    binaries=[('/home/xinnan/mycode/claude_code/vedio_scraper/ffmpeg_bin/ffmpeg', 'ffmpeg')],
    datas=[],
    hiddenimports=['yt_dlp', 'Crypto', 'Crypto.Cipher', 'Crypto.Cipher.AES', 'bs4', 'tqdm', 'requests', 'lxml'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'numpy', 'scipy', 'sklearn', 'pandas', 'matplotlib', 'PIL', 'Pillow', 'IPython', 'jupyter', 'notebook', 'tkinter', 'test', 'unittest', 'tensorboard', 'sympy', 'nvidia', 'triton', 'openpyxl', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='video_scraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
