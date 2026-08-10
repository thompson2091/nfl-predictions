#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")

from src.models.trainer import train_all

if __name__ == "__main__":
    train_all()
