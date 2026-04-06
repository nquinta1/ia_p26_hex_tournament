# Torneo de Hex — IA Primavera 2026 ITAM

Torneo de estrategias de Hex para el curso de Inteligencia Artificial.

Tu equipo implementa **una sola estrategia** que juega Hex en un tablero de **11x11** en dos variantes: **classic** y **dark** (fog of war). El framework descubre todas las estrategias, las enfrenta contra 6 niveles de dificultad, y genera calificaciones automaticamente.

---

## Reglas de Hex

Hex se juega en un tablero romboidal de hexagonos. Dos jugadores se alternan colocando piedras:

- **Negro (Player 1)**: conecta el borde **superior** (fila 0) con el borde **inferior** (fila N-1).
- **Blanco (Player 2)**: conecta el borde **izquierdo** (columna 0) con el borde **derecho** (columna N-1).

**Reglas:**
- No hay capturas — las piedras son permanentes.
- El primer jugador en conectar sus dos bordes gana.
- **No hay empates** en Hex (la geometria hexagonal lo garantiza).
- Cada celda tiene **6 vecinos**: `(-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0)`.

**Tablero 11x11**: 121 celdas. Espacio de estados enorme — minimax puro es inviable. Necesitas MCTS, heuristicas, o tecnicas avanzadas.

---

## Dos variantes

### Classic Hex
Tablero vacio al inicio. Informacion perfecta — ambos jugadores ven todo.

### Dark Hex (Fog of War)
Cada jugador **solo ve sus propias piedras** y las piedras del oponente que ha descubierto por **colision**.

**Mecanica de colision:**
- Intentas jugar en `(r, c)` que ya tiene una piedra oculta del oponente.
- **Pierdes tu turno**, pero ahora puedes ver esa piedra.
- `on_move_result(move, success)` te informa: `success=True` (se coloco) o `success=False` (colision).
- `last_move` siempre es `None` en dark mode — no sabes donde jugo el oponente.

Dark Hex introduce **informacion imperfecta**: debes razonar sobre lo que no puedes ver. Tecnicas como determinizacion o Information Set MCTS son esenciales.

---

## Setup rapido

```bash
# 1. Forkea el repo y clona tu fork
git clone https://github.com/<tu-usuario>/ia_p26_hex_tournament.git
cd ia_p26_hex_tournament

# 2. Instala Docker (necesario para correr los tiers MCTS)
#    https://docs.docker.com/get-docker/

# 3. Instala dependencias locales
pip install -r requirements.txt

# 4. Corre un torneo rapido de prueba
python3 run_all.py
```

> **Nota**: Los tiers MCTS (MCTS_Tier_1 a MCTS_Tier_5) son binarios compilados que **solo corren dentro de Docker**. Contra Random puedes probar sin Docker; para todo lo demas, usa Docker.

---

## Que tienes que hacer

### 1. Crea tu equipo

```bash
cp -r estudiantes/_template estudiantes/mi_equipo
```

### 2. Edita `estudiantes/mi_equipo/strategy.py`

```python
from strategy import Strategy, GameConfig
from hex_game import get_neighbors, check_winner, shortest_path_distance, empty_cells

class MiEstrategia(Strategy):
    @property
    def name(self) -> str:
        return "MiEstrategia_mi_equipo"   # nombre unico

    def begin_game(self, config: GameConfig) -> None:
        self._size = config.board_size
        self._player = config.player
        self._opponent = config.opponent
        self._time_limit = config.time_limit

    def on_move_result(self, move, success):
        # success=True: tu piedra se coloco
        # success=False: colision (dark mode) — perdiste el turno
        pass

    def play(self, board, last_move):
        # board[r][c]: 0=vacio, 1=Negro, 2=Blanco
        # last_move: (row, col) del oponente, o None
        # Devuelve (row, col) de una celda vacia
        moves = empty_cells(board, self._size)
        return moves[0]  # reemplaza con tu logica
```

**Tu estrategia debe funcionar para ambas variantes (classic y dark).**

### 3. Prueba con Docker

```bash
# Tu estrategia contra Random (no necesita Docker)
python3 experiment.py --black "MiEstrategia_mi_equipo" --white "Random" --num-games 5 --verbose

# Tu estrategia contra tiers MCTS (requiere Docker)
docker compose run experiment \
  python experiment.py --black "MiEstrategia_mi_equipo" --white "MCTS_Tier_3" \
  --num-games 5 --verbose

# Variante dark
docker compose run experiment \
  python experiment.py --black "MiEstrategia_mi_equipo" --white "MCTS_Tier_2" \
  --variant dark --num-games 3 --verbose

# Torneo completo: tu equipo vs todos los defaults
TEAM=mi_equipo docker compose up team-tournament
```

### 4. Entrega: abre un Pull Request

```bash
git add estudiantes/mi_equipo/strategy.py
git commit -m "add strategy mi_equipo"
git push origin mi_equipo
```

Abre un **Pull Request** de tu branch hacia `main`.

**Tu PR debe contener:**
- `estudiantes/<tu_equipo>/strategy.py` — esto es lo **unico obligatorio**
- Opcionalmente: notebooks, scripts, datos en tu directorio (no seran evaluados)

**NO incluyas:**
- Cambios a archivos fuera de `estudiantes/<tu_equipo>/`
- Archivos grandes (`.pkl`, `.npy`, modelos)
- Resultados (`results/`)

---

## Solo se evalua `strategy.py`

El framework importa **unicamente** `estudiantes/<equipo>/strategy.py`. Todo tu codigo debe estar en ese archivo: una sola clase que hereda de `Strategy`.

Puedes tener otros archivos en tu directorio para desarrollo (notebooks, scripts, tablas), pero **no seran accesibles durante la evaluacion**.

---

## Que informacion recibe tu estrategia

### `begin_game(config: GameConfig)`

| Campo | Tipo | Descripcion |
|-------|------|-------------|
| `config.board_size` | `int` | Lado del tablero (11) |
| `config.variant` | `str` | `"classic"` o `"dark"` |
| `config.initial_board` | `tuple[tuple[int,...],...]` | Tablero inicial (en dark, solo tus piedras) |
| `config.player` | `int` | Tu jugador: 1 (Negro) o 2 (Blanco) |
| `config.opponent` | `int` | Numero del oponente |
| `config.time_limit` | `float` | Segundos maximos por jugada |

### `play(board, last_move) -> (row, col)`

- `board[r][c]`: 0=vacio, 1=Negro, 2=Blanco
- `last_move`: `(row, col)` del oponente, o `None` (siempre `None` en dark)
- Devuelve `(row, col)` de una celda vacia

### `on_move_result(move, success)`

- `success=True`: tu piedra se coloco
- `success=False`: colision (dark mode) — la celda tenia una piedra oculta del oponente

---

## Calificacion

### 6 niveles de dificultad

| Tier | Dificultad | Puntos si ganas |
|------|------------|-----------------|
| **Random** | Trivial | **5** |
| **MCTS_Tier_1** | Facil | **6** |
| **MCTS_Tier_2** | Media | **7** |
| **MCTS_Tier_3** | Dificil | **8** |
| **MCTS_Tier_4** | Muy dificil | **9** |
| **MCTS_Tier_5** | Experto | **10** |

Los algoritmos de cada tier son **opacos** — binarios compilados cuyo codigo no puedes ver. Solo puedes estudiar su comportamiento jugando contra ellos.

### Como se calcula tu calificacion

1. Tu estrategia juega contra cada tier en **ambas variantes** (classic + dark), alternando colores.
2. Para "ganar" contra un tier necesitas ganar la **mayoria** de las partidas combinando ambas variantes.
3. **Tu calificacion = puntos del tier mas alto que vences.**
4. Los **top 3** estudiantes por total de victorias obtienen automaticamente **10 puntos**.

| Resultado | Calificacion |
|-----------|-------------|
| No ganas contra nadie | **0** |
| Ganas contra Random | **5** |
| Ganas contra MCTS_Tier_1 | **6** |
| Ganas contra MCTS_Tier_2 | **7** |
| Ganas contra MCTS_Tier_3 | **8** |
| Ganas contra MCTS_Tier_4 | **9** |
| Ganas contra MCTS_Tier_5 **o** eres top 3 | **10** |

---

## Restricciones de recursos

| Recurso | Limite | Detalle |
|---------|--------|---------|
| **Tiempo** | **15 segundos por jugada** | Estricto via `signal.SIGALRM`. Exceder = pierdes esa partida. |
| **CPU** | **4 cores** | Enforzado via Docker |
| **Memoria** | **8 GB** | Enforzado via Docker + `resource.setrlimit` |
| **Dependencias** | Solo `numpy` + stdlib | No instales ni importes nada mas |

**Presupuesto de tiempo:**
- `begin_game()` **no** consume tu presupuesto — solo se mide `play()`.
- 15 segundos por movimiento. Un juego de ~60 movimientos (~30 por jugador) = ~7.5 minutos maximo por partida.
- Si usas MCTS, controla con `time.monotonic()`:
  ```python
  import time
  t0 = time.monotonic()
  while time.monotonic() - t0 < self._time_limit * 0.9:
      # una iteracion de MCTS
      ...
  ```

---

## Comandos Docker (recomendado)

Los tiers MCTS son binarios compilados que **solo funcionan dentro de Docker**. Usa siempre Docker para pruebas contra tiers.

### Torneo

```bash
# Torneo oficial (ambas variantes, 5 games/pair)
docker compose up tournament

# Evaluacion real (10 games/pair, ambas variantes)
docker compose up real-tournament

# Solo tu equipo vs todos los defaults
TEAM=mi_equipo docker compose up team-tournament
```

### Experimento individual

```bash
# Tu estrategia contra un tier especifico (via env vars)
BLACK=MiEstrategia_mi_equipo WHITE=MCTS_Tier_3 docker compose run experiment

# Variante dark
BLACK=MiEstrategia_mi_equipo WHITE=MCTS_Tier_4 VARIANT=dark docker compose run experiment

# O con el comando directo (mas flexible)
docker compose run experiment \
  python experiment.py --black "MiEstrategia_mi_equipo" --white "MCTS_Tier_3" \
  --num-games 5 --verbose
```

### Sin Docker (solo Random)

```bash
# Contra Random (no necesita Docker)
python3 experiment.py --black "MiEstrategia_mi_equipo" --white "Random" --num-games 5 --verbose

# Torneo rapido (solo Random disponible sin Docker)
python3 run_all.py
```

### Opciones de `run_all.py`

```bash
python3 run_all.py                          # rapido (classic, 3 games/pair)
python3 run_all.py --official               # ambas variantes, 5 games/pair
python3 run_all.py --team mi_equipo         # solo tu equipo vs defaults
python3 run_all.py --real                   # evaluacion (10 games/pair)
python3 run_all.py --real --num-games 20    # evaluacion, 20 games/pair
```

---

## Errores comunes

### Tu estrategia no aparece
- Verifica: `estudiantes/<tu_equipo>/strategy.py` (nombre exacto).
- Tu clase debe heredar de `Strategy`.
- El directorio **no** debe empezar con `_`.

### Timeout
- El timeout es **estricto**: si `play()` tarda mas de 15 segundos, pierdes esa partida.
- Usa `time.monotonic()` para controlar tu presupuesto (deja un margen de ~10%).

### Movimiento invalido
- `play()` debe devolver `(row, col)` de una celda vacia.
- Celda ocupada o fuera de rango = pierdes la partida.

### Funciona en classic pero falla en dark
- En dark **solo ves tus piedras** + las descubiertas por colision.
- `last_move` es siempre `None`.
- Implementa `on_move_result()` para rastrear colisiones.
- Las celdas "vacias" pueden tener piedras ocultas.
- **Prueba ambas variantes antes de entregar.**

### Los tiers MCTS no cargan
- Los tiers MCTS son binarios `.so` compilados para Linux x86_64.
- **Solo funcionan dentro de Docker.** Si corres fuera de Docker, solo Random estara disponible.
- Usa `docker compose run experiment ...` para probar contra tiers.

### ImportError
- Solo `numpy` + stdlib. No importes `scipy`, `pandas`, `sklearn`, etc.
- Puedes importar: `from strategy import Strategy, GameConfig` y funciones de `hex_game`.

---

## Utilidades disponibles

```python
from hex_game import (
    get_neighbors,          # (r, c, size) -> [(nr, nc), ...]
    check_winner,           # (board, size) -> 0, 1, or 2
    shortest_path_distance, # (board, size, player) -> int (Dijkstra)
    empty_cells,            # (board, size) -> [(r, c), ...]
    render_board,           # (board, size) -> str
    NEIGHBORS,              # [(-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0)]
)
```

**Ejemplos:**
```python
dist = shortest_path_distance(board, 11, player=1)     # distancia Dijkstra
nbrs = get_neighbors(3, 5, 11)                          # vecinos de (3,5)
winner = check_winner(board, 11)                         # 0=nadie, 1=Negro, 2=Blanco
```

---

## Ideas para tu estrategia

1. **MCTS basico** — Monte Carlo Tree Search con UCT. Usa `time.monotonic()` para el presupuesto.
2. **Rollouts informados** — En vez de rollouts aleatorios, sesga hacia celdas que reducen tu distancia mas corta.
3. **Heuristica dual** — Combina tu `shortest_path_distance` con la del oponente.
4. **Puentes virtuales** — Dos piedras separadas por un gap que el oponente no puede bloquear. Prioriza completarlos.
5. **Early cutoff** — Corta rollouts antes del final y evalua con heuristica de distancia.
6. **Transposition table** — Guarda posiciones evaluadas para reutilizar entre iteraciones.
7. **Determinizacion (dark)** — Estima piedras ocultas del oponente, colocalas aleatoriamente, corre MCTS sobre ese "mundo posible".
8. **ISMCTS (dark)** — Information Set MCTS: mantiene un arbol sobre conjuntos de informacion.
9. **Exploracion de colisiones (dark)** — Colisionar revela informacion. Juega deliberadamente donde sospechas piedras ocultas.

---

## Estructura del repositorio

```
ia_p26_hex_tournament/
├── run_all.py              # Un comando para todo
├── strategy.py             # Clase base Strategy + GameConfig
├── hex_game.py             # Motor del juego (tablero, BFS, Dijkstra)
├── tournament.py           # Torneo paralelo con calificaciones
├── experiment.py           # Pruebas individuales (verbose)
├── strategies/             # Defaults compilados
│   ├── random_strat.py     #   Random (unico .py, funciona sin Docker)
│   └── mcts_tier_*_strat.*.so  #   MCTS_Tier_1..5 (binarios, solo Docker)
├── estudiantes/            # <-- AQUI VA TU ESTRATEGIA
│   ├── _template/          #     Template para copiar
│   └── <tu-equipo>/
│       └── strategy.py     #     Tu estrategia (UNICO archivo evaluado)
├── results/                # Salidas del torneo
│   ├── runs/<timestamp>/   #     Historial
│   └── latest.json         #     Ultimo torneo
├── Dockerfile
├── docker-compose.yaml
└── requirements.txt
```

---

## Outputs del torneo

| Archivo | Descripcion |
|---------|-------------|
| `results/runs/<timestamp>/tournament_results.json` | Datos completos del torneo |
| `results/latest.json` | Copia del ultimo torneo |
| `results/tournament_official.csv` | CSV partida por partida |
| `estudiantes/<equipo>/results/` | Resultados locales de tu equipo |
