# -*- coding: utf-8 -*-
"""Dua Video Generator CLI entry (F-24 refactor: god-CLI -> subcommand module)."""

import argparse
import sys

from main import DuaVideoPipeline, logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dua Video Generator")
    parser.add_argument("--dua", type=str, help="Generate video for specific dua ID")
    parser.add_argument("--theme", type=str, default="dark", help="Video theme (default: dark)")
    parser.add_argument("--effect", type=str, default="auto", help="Visual effect (default: auto)")
    parser.add_argument("--batch", action="store_true", help="Generate all missing videos")
    parser.add_argument("--list", action="store_true", help="List all dua IDs")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no video generation")
    args = parser.parse_args(argv)

    try:
        pipeline = DuaVideoPipeline()
        if args.dua:
            ok = pipeline.generate_video(args.dua, theme=args.theme, effect=args.effect, dry_run=args.dry_run)
            return 0 if ok else 1
        elif args.batch:
            pipeline._batch_mode()
        elif args.list:
            from scripts.cmd_list import cmd_list

            cmd_list()
        else:
            pipeline.interactive_menu()
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
