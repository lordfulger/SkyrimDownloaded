"""Entry point for the stand-alone .exe (PyInstaller)."""
import sys

from skyrimdl.cli import main

if __name__ == "__main__":
    sys.exit(main())
