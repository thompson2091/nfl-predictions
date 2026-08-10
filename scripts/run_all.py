#!/usr/bin/env python3
"""Run the full pipeline for both target types."""
import sys
sys.path.insert(0, ".")

from src.utils.config import get_config, _CONFIG_PATH
from src.targets.td_extractor import extract_tds
from src.targets.candidates import build_candidates
from src.features.assembler import assemble_features
from src.models.trainer import train_all
import yaml


def run_pipeline(target_type: str):
    """Run full pipeline for a single target type."""
    print(f"\n{'=' * 60}")
    print(f"  Running pipeline for: {target_type}")
    print(f"{'=' * 60}\n")

    # Temporarily set target type in config
    import src.utils.config as config_module
    config_module._config["target"]["type"] = target_type

    extract_tds(target_type)
    build_candidates(target_type)
    assemble_features()
    train_all(target_type)


if __name__ == "__main__":
    # Load config once
    cfg = get_config()

    for tt in ["first_td", "anytime_td"]:
        run_pipeline(tt)

    # Restore original config
    import src.utils.config as config_module
    config_module._config["target"]["type"] = cfg["target"]["type"]

    print("\nDone! Both pipelines complete.")
