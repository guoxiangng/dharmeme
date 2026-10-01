"""Live check of the prompt feature against the real LLM (one or two cheap calls).

    pip install -e ".[aws]"
    python scripts/smoke_llm.py "my inbox after a retreat"

Needs AWS credentials with Bedrock access. Prints the meme the model wrote, or the
fallback it produced.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dharmeme.catalog import load_catalog  # noqa: E402
from dharmeme.llm.factory import get_provider  # noqa: E402
from dharmeme.prompt import write_meme  # noqa: E402

if __name__ == "__main__":
    topic = " ".join(sys.argv[1:]) or "trying to meditate with a phone nearby"
    result = write_meme(topic, get_provider(), load_catalog())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(1 if "fallback" in result else 0)
