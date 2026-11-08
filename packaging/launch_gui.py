"""Entry point for Boxset.exe (the windowed app)."""
import sys

from boxset.__main__ import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
