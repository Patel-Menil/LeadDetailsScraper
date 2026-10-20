"""CLI entrypoint for SealAPI Lead Research Pipeline."""

import argparse
import sys
import time
from pathlib import Path

from .pipeline import ResearchPipeline
from .schemas import BatchProgress


def main():
    parser = argparse.ArgumentParser(
        prog="python -m lead_research",
        description="SealAPI Lead Research & Enrichment Pipeline using Scrapling",
    )
    parser.add_argument("--input", "-i", required=True, help="Path to input CSV or XLSX file")
    parser.add_argument("--output", "-o", default="output", help="Directory to save research outputs")
    parser.add_argument("--batch-id", "-b", default="", help="Custom batch ID (default: timestamp based)")
    parser.add_argument("--max-leads", "-m", type=int, default=None, help="Maximum number of leads to process")
    parser.add_argument("--concurrency", "-c", type=int, default=4, help="Concurrent research workers")
    parser.add_argument("--dry-run", action="store_true", help="Validate and score leads without external HTTP scraping")
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing cached profiles and re-scrape")

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file does not exist: {input_path}", file=sys.stderr)
        sys.exit(1)

    batch_id = args.batch_id or f"batch_{int(time.time())}"
    output_dir = Path(args.output)

    print("=" * 70)
    print(" SealAPI Lead Research Pipeline")
    print(f" Input File:   {input_path}")
    print(f" Output Dir:   {output_dir}")
    print(f" Batch ID:     {batch_id}")
    print(f" Dry Run Mode: {args.dry_run}")
    print(f" Concurrency:  {args.concurrency}")
    print("=" * 70)

    last_log_idx = 0

    def on_progress(p: BatchProgress):
        nonlocal last_log_idx
        while last_log_idx < len(p.recent_logs):
            print(f"[*] {p.recent_logs[last_log_idx]}")
            last_log_idx += 1

    pipeline = ResearchPipeline(output_dir=output_dir, concurrency=args.concurrency)
    progress, export_paths = pipeline.run_batch(
        batch_id=batch_id,
        input_file=input_path,
        max_leads=args.max_leads,
        dry_run=args.dry_run,
        resume=not args.no_resume,
        progress_callback=on_progress,
    )

    print("\n" + "=" * 70)
    print(" Research Summary")
    print("=" * 70)
    print(f" Total Input Leads:          {progress.total_leads}")
    print(f" Successfully Researched:    {progress.completed_count}")
    print(f" Partially Researched:       {progress.partial_count}")
    print(f" Failed Leads:               {progress.failed_count}")
    print("-" * 70)
    print(" Priority Breakdown:")
    print(f"   Priority 0 (Highest Fit): {progress.priority_counts.get('0', 0)}")
    print(f"   Priority 1 (Medium Fit):  {progress.priority_counts.get('1', 0)}")
    print(f"   Priority 2 (Lowest Fit):  {progress.priority_counts.get('2', 0)}")
    print("-" * 70)
    print(" Generated Output Files:")
    print(f"   Prioritized CSV: {export_paths.get('csv_path')}")
    print(f"   Errors CSV:      {export_paths.get('errors_path')}")
    print(f"   Manifest:        {export_paths.get('manifest_path')}")
    print(f"   JSON Profiles:   {export_paths.get('profiles_dir')}")
    print("=" * 70)


if __name__ == "__main__":
    main()
