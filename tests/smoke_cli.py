"""Optional paid connectivity check. Not collected by unittest or run by setup."""
import argparse
from pathlib import Path
import json
import tempfile
import threading
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from laboratory import providers

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-live-cli-smoke", action="store_true",
                        help="Explicitly authorize one Codex call up to 60 seconds; may consume quota")
    args = parser.parse_args(argv)
    if not args.approve_live_cli_smoke:
        parser.error("No call sent. Use the explicit approval flag only if you accept the quota cost.")
    root = Path(__file__).resolve().parents[1]
    (root / "tests/.tmp").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root / "tests/.tmp") as work:
        result = providers.run({"provider": "codex", "model": "", "web_search": False, "timeout_seconds": 60},
            "Проверка подключения AI Research Laboratory. Не используй инструменты. Ответь ровно: LAB_OK",
            Path(work) / "empty-job", threading.Event())
    summary = {"status": result["status"], "text": result["text"][:300], "usage": result["usage"],
               "dispatched": result["raw"]["dispatched"], "error": result.get("error", "")[:800]}
    (root / "tests/qa-output").mkdir(exist_ok=True)
    (root / "tests/qa-output/live-codex-diagnostic.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "tests/qa-output/live-codex-smoke.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" and "LAB_OK" in result["text"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
