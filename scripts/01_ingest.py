#!/usr/bin/env python3
import argparse
import sys
sys.path.insert(0, ".")

from src.ingest.loader import ingest_all

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-mode", action="store_true")
    args = parser.parse_args()
    ingest_all(test_mode=args.test_mode)
