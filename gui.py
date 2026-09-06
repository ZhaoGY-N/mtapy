#!/usr/bin/env python
"""mtapy GUI receiver launcher."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from mtapy_gui.app import main

if __name__ == "__main__":
    sys.exit(main())