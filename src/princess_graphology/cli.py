from __future__ import annotations

import argparse

from .engine import GraphologyEngine


def main():
    parser = argparse.ArgumentParser(prog='princess-graphology', description='Canonical handwriting measurements')
    parser.add_argument('image')
    parser.add_argument('--pretty', action='store_true')
    args = parser.parse_args()
    result = GraphologyEngine().analyze_file(args.image)
    print(result.to_json(indent=2 if args.pretty else None))


if __name__ == '__main__':
    main()
