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

## Layout of the project

| Folder | What |
|---|---|
| `trainops/` | the program |
| `tests/` | automated tests (pytest) |
| `samples/` | made-up `config.yaml`, `cars.csv`, `engines.csv` for development until the real industry data exists |
