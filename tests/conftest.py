# The pipeline scripts live in scripts/; let the tests import them (e.g. `import scrape_rosters`).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
