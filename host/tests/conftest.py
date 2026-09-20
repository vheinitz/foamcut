import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
