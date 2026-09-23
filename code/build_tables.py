#!/usr/bin/env python
import argparse

from kaf_profiti.experiments.tables import build_tables


def main():
    parser = argparse.ArgumentParser(description="Build unified experiment result tables")
    parser.add_argument("--results-dir", required=True)
    args = parser.parse_args()
    build_tables(args.results_dir)


if __name__ == "__main__":
    main()
