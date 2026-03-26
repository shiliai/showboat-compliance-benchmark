#!/usr/bin/env python3
import argparse
import glob
import json
import os
from pathlib import Path
from typing import Dict, List, Any


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Compare showboat benchmark reports across models")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table")
    parser.add_argument("--case-matrix", action="store_true", help="Include per-case scores matrix")
    args = parser.parse_args()

    report_paths = sorted(glob.glob(os.path.join(args.reports_dir, "report-*.json")))
    if not report_paths:
        raise SystemExit("No report-*.json files found")

    rows: List[Dict[str, Any]] = []
    case_ids: List[str] = []
    for path in report_paths:
        data = load_json(Path(path))
        summary = data["summary"]
        case_scores = {r["id"]: r["score"] for r in data["results"]}
        if not case_ids:
            case_ids = [r["id"] for r in data["results"]]
        rows.append({
            "report": os.path.basename(path),
            "model": os.path.basename(path).replace("report-", "").replace(".json", ""),
            "score": summary["score"],
            "max_score": summary["max_score"],
            "percent": summary["percent"],
            "passed_cases": summary["passed_cases"],
            "total_cases": summary["total_cases"],
            "case_scores": case_scores,
        })

    rows.sort(key=lambda r: r["percent"], reverse=True)

    if args.format == "json":
        out = {"models": rows}
        if args.case_matrix:
            out["case_ids"] = case_ids
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if args.format == "csv":
        headers = ["model", "percent", "passed_cases", "total_cases", "score", "max_score"]
        if args.case_matrix:
            headers += case_ids
        print(",".join(headers))
        for row in rows:
            values = [
                row["model"],
                str(row["percent"]),
                str(row["passed_cases"]),
                str(row["total_cases"]),
                str(row["score"]),
                str(row["max_score"]),
            ]
            if args.case_matrix:
                values += [str(row["case_scores"].get(cid, "")) for cid in case_ids]
            print(",".join(values))
        return

    print("MODEL                                    %     PASS     SCORE")
    print("-" * 68)
    for row in rows:
        print(f"{row['model']:<40} {row['percent']:>6.2f}  {row['passed_cases']:>2}/{row['total_cases']:<2}   {row['score']:>3}/{row['max_score']}")

    if args.case_matrix:
        print("\nPer-case score matrix:")
        header = ["MODEL"] + case_ids
        print("\t".join(header))
        for row in rows:
            vals = [row["model"]] + [str(row["case_scores"].get(cid, "")) for cid in case_ids]
            print("\t".join(vals))


if __name__ == "__main__":
    main()
