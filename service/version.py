#
# service/version.py
# Build-time version stamp.
#

"""
VERSION
  Normally overwritten by build/build.py right before each PyInstaller build
  (via BUILD_VERSION env var), then restored to "dev" afterwards to keep the
  repo's working tree clean. Running from source shows "dev", making it obvious
  this isn't a packaged release.
"""

VERSION = "dev"
