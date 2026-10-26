import sys

if sys.version_info < (3, 9):
    sys.exit("Gimmick Bench needs Python 3.9 or newer.")

from .cli import main

sys.exit(main())
