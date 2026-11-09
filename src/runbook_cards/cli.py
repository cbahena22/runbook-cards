"""runbook-cards command line: demo, build, check, eval."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .budget import Budget, BudgetError
from .card import CardError, load_cards
from .config import load_config
from .evals import EvalError, render_md, run_eval
from .llm import Gateway, LiveBatch, LiveSync, LlmError, Replay, Store
from .packs import PACKS, get_pack
from .packs.base import PackError
from .paths import CARDS_DIR, EVALS_DIR, PACKS_DIR, SITE_DIR, rel
from .site import build_site
from .validate import validate


def _cards_dir(pack: str, given: str | None) -> Path:
    return Path(given) if given else CARDS_DIR / pack


def _load(pack_name: str):
    pack = get_pack(pack_name)
    units = {u.unit_id: u for u in pack.units(pack.load(PACKS_DIR / pack_name))}
    return pack, units


def _problems(pack, units, cards) -> tuple[list[str], int]:
    """FAIL lines for a list of cards, and how many cards failed."""
    lines: list[str] = []
    failed = 0
    for card in cards:
        unit = units.get(str(card.get("card_id")))
        if unit is None:
            lines.append(f"FAIL {card.get('card_id')}: no such unit in pack {pack.name}")
            failed += 1
            continue
        found = validate(card, unit, pack)
        lines += [f"FAIL {unit.unit_id}: {p}" for p in found]
        failed += bool(found)
    return lines, failed


def cmd_check(pack_name: str, cards_dir: str | None, complete: bool = False) -> int:
    pack, units = _load(pack_name)
    directory = _cards_dir(pack_name, cards_dir)
    cards = load_cards(directory)
    ids = [str(c.get("card_id")) for c in cards]
    extra = [f"FAIL {d}: more than one card with this id" for d in sorted({i for i in ids if ids.count(i) > 1})]
    if complete:
        extra += [f"FAIL {u}: no card for this unit" for u in sorted(set(units) - set(ids))]
    lines, failed = _problems(pack, units, cards)
    for line in extra + lines:
        print(line)
    print(f"{pack_name}: {len(cards) - failed} of {len(cards)} cards pass in {rel(directory)} ({len(units)} units)")
    return 1 if (extra or failed) else 0


def cmd_build(pack_name: str, cards_dir: str | None, out: str | None) -> int:
    pack, units = _load(pack_name)
    directory = _cards_dir(pack_name, cards_dir)
    cards = load_cards(directory)
    if not cards:
        print(f"no cards in {rel(directory)}")
        return 1
    lines, failed = _problems(pack, units, cards)
    if failed:  # never render a card that does not validate
        for line in lines:
            print(line)
        print(f"{pack_name}: {failed} card(s) fail the check; page not built")
        return 1
    target = Path(out) if out else SITE_DIR / f"{pack_name}.html"
    build_site(pack_name, cards, target)
    print(f"{pack_name}: {len(cards)} cards -> {rel(target)}")
    return 0


def cmd_eval(a: argparse.Namespace) -> int:
    cfg = load_config()
    if (a.only or a.limit is not None) and not a.cards:
        raise LlmError("--only / --limit need --cards DIR (a probe never writes into the committed cards/)")
    cards_root = Path(a.cards) if a.cards else None
    results_dir = Path(a.results) if a.results else (cards_root / "results" if cards_root else EVALS_DIR / "results")
    spot = EVALS_DIR / "spot_check.csv" if not a.cards and not a.results else results_dir / "spot_check.csv"
    if a.replay:
        directory = Path(a.replay)
        store, client, budget = Store(directory, readonly=True), Replay(), None
    else:
        if a.budget is None:
            raise LlmError("--live needs --budget USD (there is no default)")
        if not a.record:
            raise LlmError("--live needs --record DIR")
        directory = Path(a.record)
        store = Store(directory)
        budget = Budget(a.budget, cfg.price_in, cfg.price_out, spent=store.total_cost(cfg))
        client = LiveBatch(cfg) if a.batch else LiveSync(cfg)
    res = run_eval(Gateway(client, store, cfg, budget), cfg, directory.resolve().name, cards_root, results_dir, spot,
                   only=a.only, limit=a.limit)
    print(render_md(res))
    print(f"results: {rel(results_dir / (res['run_id'] + '.md'))}")
    return 0


def cmd_demo() -> int:
    parts = []
    for name in PACKS:
        directory = CARDS_DIR / name
        cards = load_cards(directory) if directory.is_dir() else []
        if not cards:
            print(f"no committed cards for {name} yet (run the recorded eval first)")
            return 1
        build_site(name, cards, SITE_DIR / f"{name}.html")
        parts.append(f"{name}: {len(cards)} cards")
    print(", ".join(parts))
    print("open site/security.html and site/helpdesk.html in a browser")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="runbook-cards")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="build both pages from the committed cards ($0, no key)")
    for name, helptext in (("build", "cards -> site/<pack>.html"), ("check", "validate every card of a pack")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--pack", required=True, choices=sorted(PACKS))
        p.add_argument("--cards", default=None, help="cards directory (default: cards/<pack>)")
        if name == "build":
            p.add_argument("--out", default=None, help="output file (default: site/<pack>.html)")
        if name == "check":
            p.add_argument("--complete", action="store_true", help="also fail for a unit that has no card")
    ev = sub.add_parser("eval", help="draft every unit, write cards, score against the answer key")
    mode = ev.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", metavar="DIR", help="re-run from a recorded store ($0, no key, no network)")
    mode.add_argument("--live", action="store_true", help="call the provider (needs ANTHROPIC_API_KEY, --budget, --record)")
    ev.add_argument("--budget", type=float, default=None, help="hard USD limit for --live (no default)")
    ev.add_argument("--record", metavar="DIR", default=None, help="store directory for --live (run id = its name)")
    ev.add_argument("--batch", action="store_true", help="use the batch API instead of the default sync client")
    ev.add_argument("--only", metavar="UNIT_ID", action="append", default=None,
                    help="probe: draft only this unit (repeatable); no spot-check sheet is written")
    ev.add_argument("--limit", type=int, default=None, help="probe: draft at most N units (security first, then helpdesk)")
    ev.add_argument("--cards", default=None, help="write cards to DIR/<pack>/ (default: cards/<pack>/)")
    ev.add_argument("--results", default=None, help="results directory (default: evals/results)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "demo":
            return cmd_demo()
        if a.cmd == "build":
            return cmd_build(a.pack, a.cards, a.out)
        if a.cmd == "eval":
            return cmd_eval(a)
        return cmd_check(a.pack, a.cards, a.complete)
    except (PackError, CardError, LlmError, BudgetError, EvalError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
