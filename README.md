# TrainOps

Digital train operations for the layout: car roster, industry spot demand,
train planning and session work lists. The design lives in
`digital-train-operations-full-spec_v<version>.md` (latest version wins).

## Setup (Windows, Python 3.13)

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Run the tests

```
.venv\Scripts\python -m pytest
```

## Simulate many days

Plays the railroad automatically, checks it after every signal, and reports
train lengths, overload trains, spot waits and yard use. Use it to tune the
industry configuration.

```
.venv\Scripts\python -m trainops simulate --days 365
.venv\Scripts\python -m trainops simulate --days 200 --seed 7 --skip-chance 0.2 --bad-order-chance 0.1
.venv\Scripts\python -m trainops simulate --config my-config.yaml --cars my-cars.csv --engines my-engines.csv
```

## Run sessions by hand

Shows the current job's list and numbered buttons; type a number to send that
signal (`s` = spot states, `l` = every list, `q` = quit). The state is saved in
`trainops.db` after every signal, so you can quit and carry on later.

```
.venv\Scripts\python -m trainops play --cold-start     (first time, or to start over)
.venv\Scripts\python -m trainops play                  (carry on)
```

Both commands use the files in `samples/` unless given `--config`, `--cars`
and `--engines`.

## Layout of the project

| Folder | What |
|---|---|
| `trainops/` | the program |
| `tests/` | automated tests (pytest) |
| `samples/` | made-up `config.yaml`, `cars.csv`, `engines.csv` for development until the real industry data exists |
