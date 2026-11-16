"""Import this first in any script that prints. A normal Windows console is cp1252 and raises
UnicodeEncodeError on Arabic; this makes stdout/stderr UTF-8 so printing can never crash the program."""
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001  not a text stream
        pass
