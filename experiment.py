#!/usr/bin/env python3
"""Run a single match between two strategies with detailed output.

Shows the board after every move — ideal for debugging and development.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from strategy import Strategy, GameConfig
from strategies import discover_strategies
from hex_game import HexGame

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _find_strategy(name: str, team: str | None = None) -> type[Strategy]:
    if team:
        from strategies import _discover_builtin, _discover_students
        classes = _discover_builtin() + _discover_students(team_filter=team)
    else:
        classes = discover_strategies()
    for cls in classes:
        if cls().name.lower() == name.lower():
            return cls
    available = [cls().name for cls in classes]
    print(f"Strategy '{name}' not found. Available: {available}", file=sys.stderr)
    sys.exit(1)


def run_match(
    black_strat: Strategy,
    white_strat: Strategy,
    board_size: int = 11,
    variant: str = "classic",
    seed: int = 42,
    verbose: bool = False,
    move_timeout: float = 10.0,
) -> dict:
    """Play a single game between two strategies.

    Returns a dict with game details.
    """
    import time

    is_dark = variant == "dark"

    game = HexGame(
        size=board_size,
        variant=variant,
        seed=seed,
    )

    # Notify strategies — each gets their own view
    for strat, player_num in [(black_strat, 1), (white_strat, 2)]:
        config = GameConfig(
            board_size=board_size,
            variant=variant,
            initial_board=game.get_view(player_num),
            player=player_num,
            opponent=3 - player_num,
            time_limit=move_timeout,
        )
        strat.begin_game(config)

    if verbose:
        print(f"\n{'='*50}")
        print(f"  {black_strat.name} (Black) vs {white_strat.name} (White)")
        print(f"  Board: {board_size}×{board_size}  Variant: {variant}")
        if is_dark:
            print(f"  FOG OF WAR: each player sees only their own stones")
        print(f"{'='*50}")
        print(f"\nInitial board (god view):")
        print(game.render())

    move_log = []
    last_successful: dict[int, tuple[int, int] | None] = {1: None, 2: None}

    while not game.is_over:
        current = game.current_player
        opponent_num = 3 - current
        strat = black_strat if current == 1 else white_strat
        color = "Black" if current == 1 else "White"

        # Board view and last_move depend on variant
        board_view = game.get_view(current)
        last = None if is_dark else last_successful.get(opponent_num)

        t0 = time.monotonic()
        move = strat.play(board_view, last)
        elapsed = time.monotonic() - t0

        try:
            winner_result, collision = game.play(move[0], move[1])
        except (ValueError, RuntimeError) as e:
            if verbose:
                print(f"\n  {color} ({strat.name}) made INVALID move {move}: {e}")
                print(f"  {color} FORFEITS. {'White' if current == 1 else 'Black'} wins!")
            return {
                "black": black_strat.name,
                "white": white_strat.name,
                "winner": white_strat.name if current == 1 else black_strat.name,
                "winner_color": 3 - current,
                "moves": game.move_count,
                "forfeit": True,
                "move_log": move_log,
            }

        # Notify strategy of result
        strat.on_move_result(move, not collision)
        if not collision:
            last_successful[current] = move

        move_log.append({
            "move_num": game.move_count,
            "player": color,
            "strategy": strat.name,
            "cell": list(move),
            "time_s": round(elapsed, 3),
            "collision": collision,
        })

        if verbose:
            collision_str = " COLLISION!" if collision else ""
            print(f"\n  Move {game.move_count}: {color} ({strat.name}) → "
                  f"({move[0]}, {move[1]})  [{elapsed:.2f}s]{collision_str}")
            if is_dark:
                print(f"  God view:")
            print(game.render())

    winner_color = game.winner
    winner_name = black_strat.name if winner_color == 1 else white_strat.name
    winner_color_str = "Black" if winner_color == 1 else "White"

    # Notify strategies
    black_strat.end_game(game.board, winner_color, 1)
    white_strat.end_game(game.board, winner_color, 2)

    if verbose:
        print(f"\n  WINNER: {winner_name} ({winner_color_str}) in {game.move_count} moves")

    return {
        "black": black_strat.name,
        "white": white_strat.name,
        "winner": winner_name,
        "winner_color": winner_color,
        "moves": game.move_count,
        "forfeit": False,
        "move_log": move_log,
    }


def run_series(
    black_strat: Strategy,
    white_strat: Strategy,
    board_size: int = 11,
    variant: str = "classic",
    num_games: int = 5,
    seed: int = 42,
    verbose: bool = False,
    move_timeout: float = 10.0,
) -> list[dict]:
    """Play a series of games, alternating colors."""
    import random as _random

    rng = _random.Random(seed)
    results = []

    for i in range(num_games):
        game_seed = rng.randint(0, 2**31)
        if i % 2 == 0:
            b_strat, w_strat = black_strat, white_strat
        else:
            b_strat, w_strat = white_strat, black_strat

        if verbose:
            print(f"\n{'#'*50}")
            print(f"  Game {i+1}/{num_games}")
            print(f"{'#'*50}")

        result = run_match(
            black_strat=b_strat,
            white_strat=w_strat,
            board_size=board_size,
            variant=variant,
            seed=game_seed,
            verbose=verbose,
            move_timeout=move_timeout,
        )
        results.append(result)

    return results


def print_series_summary(results: list[dict], strat_a: str, strat_b: str) -> None:
    a_wins = sum(1 for r in results if r["winner"] == strat_a)
    b_wins = sum(1 for r in results if r["winner"] == strat_b)
    total = len(results)

    print(f"\n=== Series: {strat_a} vs {strat_b} — {total} games ===")
    print(f"  {strat_a}: {a_wins} wins ({100*a_wins/total:.0f}%)")
    print(f"  {strat_b}: {b_wins} wins ({100*b_wins/total:.0f}%)")
    avg_moves = sum(r["moves"] for r in results) / total if total else 0
    print(f"  Average game length: {avg_moves:.1f} moves")


def main() -> None:
    parser = argparse.ArgumentParser(description="Single Hex match experiment")
    parser.add_argument("--black", type=str, default="Random",
                        help="Black strategy name (default: Random)")
    parser.add_argument("--white", type=str, default="Random",
                        help="White strategy name (default: Random)")
    parser.add_argument("--board-size", type=int, default=11,
                        help="Board side length (default: 11)")
    parser.add_argument("--variant", choices=["classic", "dark"], default="classic",
                        help="Game variant: classic or dark (fog of war) (default: classic)")
    parser.add_argument("--num-games", type=int, default=5,
                        help="Number of games in the series (default: 5)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    parser.add_argument("--move-timeout", type=float, default=15.0,
                        help="Max seconds per move (default: 15.0)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print board after every move")
    parser.add_argument("--json", type=str, default=None,
                        help="Save results as JSON")
    parser.add_argument("--team", type=str, default=None,
                        help="Team name (resolves strategy from team dir)")
    args = parser.parse_args()

    if args.team:
        out_dir = Path(__file__).resolve().parent / "estudiantes" / args.team / "results"
    else:
        out_dir = RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    black_cls = _find_strategy(args.black, team=args.team)
    white_cls = _find_strategy(args.white, team=args.team)
    black_strat = black_cls()
    white_strat = white_cls()

    print(f"Black: {black_strat.name}")
    print(f"White: {white_strat.name}")
    print(f"Board: {args.board_size}×{args.board_size}  Variant: {args.variant}")

    results = run_series(
        black_strat=black_strat,
        white_strat=white_strat,
        board_size=args.board_size,
        variant=args.variant,

        num_games=args.num_games,
        seed=args.seed,
        verbose=args.verbose,
        move_timeout=args.move_timeout,
    )

    print_series_summary(results, black_strat.name, white_strat.name)

    # JSON output
    json_path = Path(args.json) if args.json else out_dir / f"experiment_{black_strat.name}_vs_{white_strat.name}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "black": black_strat.name,
        "white": white_strat.name,
        "config": {
            "board_size": args.board_size,
            "variant": args.variant,
            "num_games": args.num_games,
            "seed": args.seed,
            "move_timeout": args.move_timeout,
        },
        "games": results,
    }
    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON saved to {json_path}")


if __name__ == "__main__":
    main()
