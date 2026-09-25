from __future__ import annotations
import argparse
import json
from .engine import GraphologyEngine

def main():
    parser = argparse.ArgumentParser(prog="princess-graphology", description="Deterministic handwriting measurement bootstrap")
    parser.add_argument("image")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    result = GraphologyEngine().analyze_file(args.image).to_dict()
    print(json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False))

if __name__ == "__main__":
    main()
