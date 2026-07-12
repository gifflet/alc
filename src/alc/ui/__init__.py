# alc.ui — Optional web backend for `alc ui` (requires the `ui` extra).
#
# Intentionally imports nothing at package import time: create_app pulls in
# fastapi and must stay behind the lazy import in alc.cli so `alc` works
# without the `ui` extra installed.
