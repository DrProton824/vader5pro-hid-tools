"""
Build-time version stamp.

VERSION is normally overwritten by build/build.py right before each
PyInstaller build (see the BUILD_VERSION env var it reads), then
restored back to "dev" afterwards so the repo's working tree stays
clean. Running from source without going through build.py simply shows
"dev", making it obvious this isn't a packaged release.
"""

VERSION = "dev"
