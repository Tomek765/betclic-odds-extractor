from __future__ import annotations

import argparse
import sys

from .engine import build_context
from .packet_parser import PacketParseError, parse_packet_file
from .report import write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="APEX Market Context Engine V1")
    parser.add_argument("--input", required=True, help="Ścieżka do BETCLIC_FULL_ODDS_PACKET.txt")
    parser.add_argument("--output-dir", required=True, help="Katalog wynikowy")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        context = build_context(parse_packet_file(args.input))
        json_path, text_path = write_outputs(context, args.output_dir)
    except (OSError, PacketParseError, ValueError) as exc:
        print(f"CONTEXT_ENGINE_STATUS=BLOCKED; ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        return 2
    print(f"CONTEXT_ENGINE_STATUS={context.status}")
    print(f"JSON={json_path}")
    print(f"TEXT={text_path}")
    if context.blocked_reasons:
        print("REASONS=" + "|".join(context.blocked_reasons))
    return 0 if context.status in {"PASS", "PASS_WITH_QUARANTINE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
