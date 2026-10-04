from __future__ import annotations

import argparse
import json
from pathlib import Path

from super_ai.evaluation import evaluate_records, load_evaluation_records, render_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure AIOps Agent evaluation results.")
    parser.add_argument("dataset", type=Path, help="Versioned evaluation result JSONL file")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    metrics = evaluate_records(load_evaluation_records(args.dataset))
    json_text = json.dumps(metrics.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown_text = render_markdown(metrics) + "\n"
    if args.json_output is not None:
        args.json_output.write_text(json_text, encoding="utf-8")
    if args.markdown_output is not None:
        args.markdown_output.write_text(markdown_text, encoding="utf-8")
    print(markdown_text)


if __name__ == "__main__":
    main()
