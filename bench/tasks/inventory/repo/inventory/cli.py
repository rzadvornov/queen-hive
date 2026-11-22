"""Command line: add and list items."""

import argparse
import sys

from inventory import store


def cmd_add(args) -> None:
    items = store.load()
    items[args.sku] = store.Item(args.sku, args.name, args.quantity, args.price)
    store.save(items)


def cmd_list(args) -> None:
    for item in sorted(store.load().values(), key=lambda i: i.sku):
        print(f"{item.sku}\t{item.name}\t{item.quantity}\t{item.price:.2f}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="inventory")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("sku")
    add.add_argument("name")
    add.add_argument("quantity", type=int)
    add.add_argument("price", type=float)
    add.set_defaults(func=cmd_add)
    sub.add_parser("list").set_defaults(func=cmd_list)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    args.func(args)
