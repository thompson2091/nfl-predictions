#!/usr/bin/env python3
import argparse
import sys
sys.path.insert(0, ".")

from src.prediction.predict import predict

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--model", default=None, help="Model name (default: from config)")
    args = parser.parse_args()
    predict(args.season, args.week, args.model)
