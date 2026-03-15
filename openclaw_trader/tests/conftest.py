import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "workspace-c3po" / "setups"))

import news_directional as workspace_c3po_setups_news_directional
sys.modules["workspace_c3po_setups_news_directional"] = workspace_c3po_setups_news_directional
