#!/usr/bin/env python3
"""Run head-to-head Hex tournament between discovered strategies.

Features:
  - Auto-discovers built-in strategies AND student submissions.
  - Runs matches in parallel (one process per match).
  - Supports two variants: ``classic`` and ``dark`` (fog of war).
  - Per-move timeout enforcement via ``signal.SIGALRM``.
  - Threshold scoring: 0 / 6 / 8 / 10 based on which defaults you beat.
  - Outputs summary tables, CSV, and JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time as _time_mod
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Default baselines in difficulty order (must match strategy names)
DEFAULT_TIERS = [
    "Random",
    "MCTS_Tier_1",
    "MCTS_Tier_2",
    "MCTS_Tier_3",
    "MCTS_Tier_4",
    "MCTS_Tier_5",
]
TIER_SCORES = {
    "Random": 5,
    "MCTS_Tier_1": 6,
    "MCTS_Tier_2": 7,
    "MCTS_Tier_3": 8,
    "MCTS_Tier_4": 9,
    "MCTS_Tier_5": 10,
}


# ------------------------------------------------------------------
# Result containers
# ------------------------------------------------------------------

@dataclass
class MatchResult:
    """Result of a single game between two strategies."""
    black_strategy: str
    white_strategy: str
    winner_strategy: str
    winner_color: int  # 1=Black, 2=White
    variant: str
    board_size: int
    num_moves: int
    black_timed_out: bool = False
    white_timed_out: bool = False


@dataclass
class TournamentResults:
    matches: list[MatchResult] = field(default_factory=list)

    def to_csv(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "black_strategy", "white_strategy", "winner_strategy",
                "winner_color", "variant", "board_size", "num_moves",
                "black_timed_out", "white_timed_out",
            ])
            for m in self.matches:
                writer.writerow([
                    m.black_strategy, m.white_strategy, m.winner_strategy,
                    m.winner_color, m.variant, m.board_size, m.num_moves,
                    int(m.black_timed_out), int(m.white_timed_out),
                ])

    def print_summary(self) -> None:
        from collections import defaultdict

        # Win counts per strategy
        wins: dict[str, int] = defaultdict(int)
        losses: dict[str, int] = defaultdict(int)
        games: dict[str, int] = defaultdict(int)

        for m in self.matches:
            games[m.black_strategy] += 1
            games[m.white_strategy] += 1
            wins[m.winner_strategy] += 1
            loser = m.white_strategy if m.winner_strategy == m.black_strategy else m.black_strategy
            losses[loser] += 1

        all_strats = sorted(set(games.keys()))

        print(f"\n{'Strategy':<25} {'Games':>6} {'Wins':>6} {'Losses':>7} {'Win%':>6}")
        print("-" * 55)
        ranking = sorted(all_strats, key=lambda s: -wins[s] / max(games[s], 1))
        for name in ranking:
            g = games[name]
            w = wins[name]
            l = losses[name]
            rate = 100 * w / g if g else 0
            print(f"{name:<25} {g:>6} {w:>6} {l:>7} {rate:>5.1f}%")
        print()

    def print_matchup_table(self) -> None:
        """Print head-to-head results between each pair of strategies."""
        from collections import defaultdict

        # wins[a][b] = number of games a won against b
        w: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        g: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for m in self.matches:
            a, b = m.black_strategy, m.white_strategy
            g[a][b] += 1
            g[b][a] += 1
            winner = m.winner_strategy
            loser = b if winner == a else a
            w[winner][loser] += 1

        strats = sorted(set(s for pair in g.values() for s in pair) | set(g.keys()))

        print(f"\n{'MATCHUP TABLE (wins / games)':^60}")
        header = f"{'':20}" + "".join(f"{s[:12]:>14}" for s in strats)
        print(header)
        print("-" * len(header))
        for a in strats:
            row = f"{a[:19]:<20}"
            for b in strats:
                if a == b:
                    row += f"{'---':>14}"
                else:
                    total = g[a].get(b, 0)
                    won = w[a].get(b, 0)
                    row += f"{f'{won}/{total}':>14}" if total > 0 else f"{'':>14}"
            print(row)
        print()

    def to_json(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {"matches": [asdict(m) for m in self.matches]}
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------
# Worker: play a single game between two strategies
# ------------------------------------------------------------------

def _apply_resource_limits(memory_mb: int = 8192) -> None:
    """Set memory limit for the worker process."""
    import resource as _resource

    mem_bytes = memory_mb * 1024 * 1024
    try:
        _resource.setrlimit(_resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except (ValueError, OSError):
        try:
            _resource.setrlimit(_resource.RLIMIT_DATA, (mem_bytes, mem_bytes))
        except (ValueError, OSError):
            pass


def _run_match_worker(
    black_info: tuple[str, str],
    white_info: tuple[str, str],
    board_size: int,
    variant: str,
    seed: int,
    move_timeout: float = 15.0,
    memory_limit_mb: int = 8192,
) -> MatchResult:
    """Play one game between two strategies. Executed in a subprocess."""
    import importlib
    import importlib.util
    import os
    import signal as _signal
    import sys as _sys
    from pathlib import Path as _Path

    # Apply resource limits
    _apply_resource_limits(memory_limit_mb)

    code_dir = str(_Path(__file__).resolve().parent)
    if code_dir not in _sys.path:
        _sys.path.insert(0, code_dir)

    from strategy import Strategy as _Strategy, GameConfig
    from hex_game import HexGame

    def _load_strategy(info: tuple[str, str]) -> _Strategy:
        source, cls_name = info
        if source == "__builtin__":
            from strategies import _discover_builtin
            for cls in _discover_builtin():
                if cls.__name__ == cls_name:
                    return cls()
            raise RuntimeError(f"Built-in strategy class {cls_name} not found")
        else:
            spec = importlib.util.spec_from_file_location(f"_worker_{cls_name}", source)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Cannot load {source}")
            mod = importlib.util.module_from_spec(spec)
            _sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (isinstance(obj, type) and issubclass(obj, _Strategy)
                        and obj is not _Strategy and obj.__name__ == cls_name):
                    return obj()
            raise RuntimeError(f"Class {cls_name} not found in {source}")

    black_strat = _load_strategy(black_info)
    white_strat = _load_strategy(white_info)

    # Create game
    game = HexGame(
        size=board_size,
        variant=variant,
        seed=seed,
    )

    # Timeout handling
    class _MoveTimeout(Exception):
        pass

    def _alarm_handler(signum, frame):
        raise _MoveTimeout()

    _signal.signal(_signal.SIGALRM, _alarm_handler)

    is_dark = variant == "dark"

    # Notify strategies — each player gets their own view
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

    black_timed_out = False
    white_timed_out = False

    # Track last successful move per player (for classic last_move)
    last_successful: dict[int, tuple[int, int] | None] = {1: None, 2: None}

    while not game.is_over:
        current = game.current_player
        opponent_num = 3 - current
        strat = black_strat if current == 1 else white_strat

        # Board view: in dark mode, player's view; in classic, full board
        board_state = game.get_view(current)
        # last_move: in dark mode, None (can't see opponent); in classic, opponent's last move
        last = None if is_dark else last_successful.get(opponent_num)

        timeout_secs = max(1, int(move_timeout + 1))
        _signal.alarm(timeout_secs)
        try:
            move = strat.play(board_state, last)
            _signal.alarm(0)
        except _MoveTimeout:
            _signal.alarm(0)
            if current == 1:
                black_timed_out = True
                winner_color = 2
                winner_name = white_strat.name
            else:
                white_timed_out = True
                winner_color = 1
                winner_name = black_strat.name
            return MatchResult(
                black_strategy=black_strat.name,
                white_strategy=white_strat.name,
                winner_strategy=winner_name,
                winner_color=winner_color,
                variant=variant,
                board_size=board_size,
                num_moves=game.move_count,
                black_timed_out=black_timed_out,
                white_timed_out=white_timed_out,
            )
        except Exception:
            _signal.alarm(0)
            if current == 1:
                winner_color = 2
                winner_name = white_strat.name
            else:
                winner_color = 1
                winner_name = black_strat.name
            return MatchResult(
                black_strategy=black_strat.name,
                white_strategy=white_strat.name,
                winner_strategy=winner_name,
                winner_color=winner_color,
                variant=variant,
                board_size=board_size,
                num_moves=game.move_count,
            )

        try:
            winner_result, collision = game.play(move[0], move[1])
        except (ValueError, RuntimeError):
            # Invalid move = forfeit (e.g., playing on own stone)
            if current == 1:
                winner_color = 2
                winner_name = white_strat.name
            else:
                winner_color = 1
                winner_name = black_strat.name
            return MatchResult(
                black_strategy=black_strat.name,
                white_strategy=white_strat.name,
                winner_strategy=winner_name,
                winner_color=winner_color,
                variant=variant,
                board_size=board_size,
                num_moves=game.move_count,
            )

        # Notify strategy of move result
        strat.on_move_result(move, not collision)
        if not collision:
            last_successful[current] = move

    # Game ended normally
    winner_color = game.winner
    winner_name = black_strat.name if winner_color == 1 else white_strat.name

    # Notify strategies with FULL board (regardless of variant)
    final_board = game.board
    black_strat.end_game(final_board, winner_color, 1)
    white_strat.end_game(final_board, winner_color, 2)

    return MatchResult(
        black_strategy=black_strat.name,
        white_strategy=white_strat.name,
        winner_strategy=winner_name,
        winner_color=winner_color,
        variant=variant,
        board_size=board_size,
        num_moves=game.move_count,
    )


# ------------------------------------------------------------------
# Tournament runner
# ------------------------------------------------------------------

def run_tournament(
    strategies_info: list[tuple[tuple[str, str], str]],
    board_size: int = 11,
    variant: str = "classic",
    num_games: int = 5,
    seed: int = 42,
    max_workers: int | None = None,
    move_timeout: float = 15.0,
    memory_limit_mb: int = 8192,
    eval_mode: bool = False,
) -> TournamentResults:
    """Run a tournament.

    Parameters
    ----------
    strategies_info : list
        Each element is ((source, class_name), display_name).
    eval_mode : bool
        If True, only student strategies play against defaults.
        If False, full round-robin (all pairs).
    """
    import os as _os

    rng = random.Random(seed)

    if max_workers is None:
        max_workers = min(8, _os.cpu_count() or 4)

    # Build match schedule
    matches_to_run: list[tuple[tuple[str, str], str, tuple[str, str], str, int]] = []
    # Each match: (info_a, name_a, info_b, name_b, game_seed)

    strat_by_name = {name: info for info, name in strategies_info}

    if eval_mode:
        # Students vs defaults only
        defaults = {name for name in strat_by_name if name in DEFAULT_TIERS}
        students = {name for name in strat_by_name if name not in defaults}
        pairs = [(s, d) for s in students for d in defaults]
    else:
        # Round robin: all unique pairs
        names = list(strat_by_name.keys())
        pairs = [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))]

    for a_name, b_name in pairs:
        for game_idx in range(num_games):
            game_seed = rng.randint(0, 2**31)
            # Alternate colors: even games a=Black, odd games a=White
            if game_idx % 2 == 0:
                black_name, white_name = a_name, b_name
            else:
                black_name, white_name = b_name, a_name
            matches_to_run.append((
                strat_by_name[black_name], black_name,
                strat_by_name[white_name], white_name,
                game_seed,
            ))

    total_matches = len(matches_to_run)
    print(f"Running {total_matches} games "
          f"({len(pairs)} pairs × {num_games} games, "
          f"variant: {variant}, "
          f"board: {board_size}×{board_size}, "
          f"workers: {max_workers}, "
          f"timeout: {move_timeout}s/move, "
          f"memory: {memory_limit_mb}MB/match) ...", flush=True)

    results = TournamentResults()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for black_info, black_name, white_info, white_name, game_seed in matches_to_run:
            fut = executor.submit(
                _run_match_worker,
                black_info,
                white_info,
                board_size,
                variant,
                game_seed,
                move_timeout,
                memory_limit_mb,
            )
            futures[fut] = (black_name, white_name)

        completed = 0
        for fut in as_completed(futures):
            black_name, white_name = futures[fut]
            completed += 1
            try:
                match_result = fut.result()
                results.matches.append(match_result)
                timeout_str = ""
                if match_result.black_timed_out:
                    timeout_str = " [Black TIMEOUT]"
                elif match_result.white_timed_out:
                    timeout_str = " [White TIMEOUT]"
                if completed % 10 == 0 or completed == total_matches:
                    print(f"  [{completed}/{total_matches}] "
                          f"{match_result.black_strategy} vs {match_result.white_strategy} → "
                          f"{match_result.winner_strategy} wins ({match_result.num_moves} moves)"
                          f"{timeout_str}", flush=True)
            except Exception as exc:
                print(f"  [{completed}/{total_matches}] "
                      f"{black_name} vs {white_name} FAILED: {exc}", file=sys.stderr)

    return results


# ------------------------------------------------------------------
# Scoring: threshold-based grades
# ------------------------------------------------------------------

def compute_grades(
    results: TournamentResults,
    num_games: int = 5,
) -> list[dict]:
    """Compute threshold-based grades for student strategies.

    Scoring (6-tier system):
      - Beat Random: 5 pts
      - Beat MCTS_Tier_1: 6 pts
      - Beat MCTS_Tier_2: 7 pts
      - Beat MCTS_Tier_3: 8 pts
      - Beat MCTS_Tier_4: 9 pts
      - Beat MCTS_Tier_5: 10 pts
      - Score is the HIGHEST threshold reached.
      - If you don't beat any default: 0 pts
      - Auto-10: Top 3 students by total wins get score 10.
    """
    from collections import defaultdict

    # wins[student][default] = count of wins
    wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    games: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_wins: dict[str, int] = defaultdict(int)

    defaults_set = set(DEFAULT_TIERS)

    for m in results.matches:
        # Identify student and default
        if m.black_strategy in defaults_set and m.white_strategy in defaults_set:
            continue  # default vs default, skip
        if m.black_strategy not in defaults_set and m.white_strategy not in defaults_set:
            continue  # student vs student, skip for grading

        if m.black_strategy in defaults_set:
            default_name = m.black_strategy
            student_name = m.white_strategy
        else:
            default_name = m.white_strategy
            student_name = m.black_strategy

        games[student_name][default_name] += 1
        if m.winner_strategy == student_name:
            wins[student_name][default_name] += 1
            total_wins[student_name] += 1

    # Compute grades — need strictly more than half
    threshold = num_games // 2 + 1  # Need to win majority (e.g., 3/5, 6/10)
    grades = []
    for student in sorted(set(wins.keys()) | set(games.keys())):
        score = 0
        beaten = []
        for tier in DEFAULT_TIERS:
            g = games[student].get(tier, 0)
            w = wins[student].get(tier, 0)
            if w >= threshold:
                score = TIER_SCORES[tier]
                beaten.append(tier)

        detail = {}
        for tier in DEFAULT_TIERS:
            g = games[student].get(tier, 0)
            w = wins[student].get(tier, 0)
            detail[tier] = f"{w}/{g}"

        grades.append({
            "strategy": student,
            "score": score,
            "beaten": beaten,
            "total_wins": total_wins[student],
            "detail": detail,
        })

    grades.sort(key=lambda x: (-x["score"], -x["total_wins"]))

    # Auto-10: top 3 students by total wins get score 10
    if len(grades) >= 1:
        win_counts = sorted(
            {g["total_wins"] for g in grades}, reverse=True,
        )
        # Find the threshold for top 3 (handle ties at 3rd place)
        top3_threshold = win_counts[min(2, len(win_counts) - 1)]
        if top3_threshold > 0:  # Don't give auto-10 for 0 wins
            for g in grades:
                if g["total_wins"] >= top3_threshold:
                    if g["score"] < 10:
                        g["score"] = 10
                        g["auto_10"] = True

    grades.sort(key=lambda x: (-x["score"], -x["total_wins"]))
    return grades


def print_grades(grades: list[dict]) -> None:
    """Print a nicely formatted grade table."""
    print(f"\n{'='*72}")
    print(f"  GRADES (threshold scoring)")
    print(f"{'='*72}")
    print(f"  {'Strategy':<25}{'Score':>7}{'Beaten':>20}  Detail")
    print(f"  {'-'*65}")
    for g in grades:
        beaten = ", ".join(g["beaten"]) if g["beaten"] else "none"
        detail = "  ".join(f"{k}: {v}" for k, v in g["detail"].items())
        auto = " (auto-10: top 3)" if g.get("auto_10") else ""
        print(f"  {g['strategy']:<25}{g['score']:>7}{beaten:>20}  {detail}{auto}")
    print()

    # Top 3 highlight
    if len(grades) >= 3:
        print("  TOP 3 (auto-10):")
        for i, g in enumerate(grades[:3]):
            medal = ["#1", "#2", "#3"][i]
            print(f"    {medal} {g['strategy']} — score: {g['score']}, "
                  f"total wins: {g['total_wins']}")
        print()


# ------------------------------------------------------------------
# Full tournament JSON export
# ------------------------------------------------------------------

def build_tournament_json(
    results: TournamentResults,
    grades: list[dict],
    config: dict,
) -> dict:
    tid = config.get("tournament_id", "tournament")
    return {
        "tournament_id": tid,
        "timestamp": datetime.now().isoformat(),
        "config": config,
        "matches": [asdict(m) for m in results.matches],
        "grades": grades,
    }


# ------------------------------------------------------------------
# Canonical rounds
# ------------------------------------------------------------------

CANONICAL_ROUNDS = [
    {"variant": "classic"},
    {"variant": "dark"},
]


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hex strategy tournament",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python tournament.py                                    # quick: classic, 5 games/pair
  python tournament.py --variant dark                     # dark hex (fog of war)
  python tournament.py --official                         # both variants (classic + dark)
  python tournament.py --official --num-games 10          # 10 games per pair per variant
  python tournament.py --team my_team                     # your team vs defaults
  python tournament.py --eval                             # students vs defaults only
""",
    )
    parser.add_argument("--board-size", type=int, default=11,
                        help="Board side length (default: 11)")
    parser.add_argument("--variant", choices=["classic", "dark"], default="classic",
                        help="Game variant: classic (full info) or dark (fog of war) (default: classic)")
    parser.add_argument("--num-games", type=int, default=5,
                        help="Games per pair (default: 5, alternating colors)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed (default: random for official, 42 otherwise)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Max parallel workers (default: auto)")
    parser.add_argument("--move-timeout", type=float, default=15.0,
                        help="Max seconds per move (default: 15.0)")
    parser.add_argument("--memory", type=int, default=8192,
                        help="Memory limit in MB per match (default: 4096)")
    parser.add_argument("--csv", type=str, default=None,
                        help="Save results CSV path")
    parser.add_argument("--json", type=str, default=None,
                        help="Save results JSON path")
    parser.add_argument("--official", action="store_true",
                        help="Run both variants (classic + dark)")
    parser.add_argument("--team", type=str, default=None,
                        help="Run only this team's strategy (+ defaults)")
    parser.add_argument("--eval", action="store_true",
                        help="Evaluation mode: students vs defaults only (no student vs student)")
    parser.add_argument("--name", type=str, default=None,
                        help="Optional human-readable tournament name")
    args = parser.parse_args()

    from strategies import _discover_builtin, _discover_students

    # Determine output directory
    if args.team:
        out_dir = Path(__file__).resolve().parent / "estudiantes" / args.team / "results"
    else:
        out_dir = RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Discover strategies
    strat_infos: list[tuple[tuple[str, str], str]] = []

    for cls in _discover_builtin():
        inst = cls()
        strat_infos.append((("__builtin__", cls.__name__), inst.name))

    for cls in _discover_students(team_filter=args.team):
        inst = cls()
        src_file = sys.modules.get(cls.__module__)
        if src_file and hasattr(src_file, "__file__") and src_file.__file__:
            strat_infos.append(((src_file.__file__, cls.__name__), inst.name))
        else:
            strat_infos.append((("__builtin__", cls.__name__), inst.name))

    if not strat_infos:
        print("No strategies found.", file=sys.stderr)
        return

    master_seed = args.seed if args.seed is not None else random.randint(0, 2**31)
    rng = random.Random(master_seed)

    if args.official:
        _run_official(args, strat_infos, out_dir, rng)
    else:
        _run_single(args, strat_infos, out_dir, rng)


def _run_single(args, strat_infos, out_dir, rng) -> None:
    """Run a single-variant tournament."""
    seed = rng.randint(0, 2**31)

    print(f"\n{'='*60}")
    print(f"  VARIANT: {args.variant}  |  BOARD: {args.board_size}×{args.board_size}")
    print(f"{'='*60}\n")

    results = run_tournament(
        strategies_info=strat_infos,
        board_size=args.board_size,
        variant=args.variant,
        num_games=args.num_games,
        seed=seed,
        max_workers=args.workers,
        move_timeout=args.move_timeout,
        memory_limit_mb=args.memory,
        eval_mode=args.eval or bool(args.team),
    )

    results.print_summary()
    results.print_matchup_table()

    grades = compute_grades(results, num_games=args.num_games)
    print_grades(grades)

    csv_path = args.csv or str(out_dir / f"tournament_{args.variant}.csv")
    results.to_csv(csv_path)
    print(f"CSV saved to {csv_path}")

    if args.json:
        json_path = args.json
    else:
        json_path = str(out_dir / f"tournament_{args.variant}.json")

    config = {
        "board_size": args.board_size,
        "variant": args.variant,
        "num_games": args.num_games,
        "move_timeout": args.move_timeout,
        "memory_limit_mb": args.memory,
    }
    data = build_tournament_json(results, grades, config)
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(json_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"JSON saved to {json_path}")


def _run_official(args, strat_infos, out_dir, rng) -> None:
    """Run the official tournament: both variants."""
    all_results = TournamentResults()

    print(f"\n{'#'*60}")
    print(f"  OFFICIAL TOURNAMENT")
    print(f"  Board: {args.board_size}×{args.board_size}")
    print(f"  Games per pair: {args.num_games}")
    print(f"  Timeout: {args.move_timeout}s/move | Memory: {args.memory}MB")
    print(f"{'#'*60}")

    for rd in CANONICAL_ROUNDS:
        variant = rd["variant"]
        round_seed = rng.randint(0, 2**31)

        print(f"\n{'='*60}")
        print(f"  ROUND: {variant}"
              + (" (fog of war)" if variant == "dark" else ""))
        print(f"{'='*60}\n")

        t0 = _time_mod.time()
        results = run_tournament(
            strategies_info=strat_infos,
            board_size=args.board_size,
            variant=variant,
            num_games=args.num_games,
            seed=round_seed,
            max_workers=args.workers,
            move_timeout=args.move_timeout,
            memory_limit_mb=args.memory,
            eval_mode=args.eval or bool(args.team),
        )
        elapsed = _time_mod.time() - t0

        results.print_summary()
        results.print_matchup_table()
        print(f"Elapsed: {elapsed:.1f}s")

        all_results.matches.extend(results.matches)

    # Overall grades
    grades = compute_grades(all_results, num_games=args.num_games * len(CANONICAL_ROUNDS))
    print_grades(grades)

    # Save
    csv_path = args.csv or str(out_dir / "tournament_official.csv")
    all_results.to_csv(csv_path)
    print(f"CSV saved to {csv_path}")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.json:
        json_path = args.json
    else:
        run_dir = out_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        json_path = str(run_dir / "tournament_results.json")

    config = {
        "tournament_id": run_id,
        "name": args.name,
        "board_size": args.board_size,
        "num_games": args.num_games,
        "move_timeout": args.move_timeout,
        "memory_limit_mb": args.memory,
        "rounds": CANONICAL_ROUNDS,
    }
    data = build_tournament_json(all_results, grades, config)
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    json_content = json.dumps(data, indent=2, ensure_ascii=False)
    Path(json_path).write_text(json_content, encoding="utf-8")
    print(f"JSON saved to {json_path}")

    latest_path = out_dir / "latest.json"
    latest_path.write_text(json_content, encoding="utf-8")
    print(f"Latest copy: {latest_path}")


if __name__ == "__main__":
    main()
