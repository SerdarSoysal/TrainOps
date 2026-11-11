"""Step 4: reading cars.csv and engines.csv."""

import pytest

from trainops import vocab as v
from trainops.rosterfiles import engine_count_problems, read_cars, read_engines


def write(tmp_path, name, text, encoding="utf-8"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


# --- the sample files ------------------------------------------------------------------


def test_sample_cars_read_cleanly(samples_dir):
    cars, problems = read_cars(samples_dir / "cars.csv")
    assert problems == []
    assert len(cars) == 65
    assert cars[0].label == "CSXT 14420"
    assert cars[0].location == v.EAST_STAGING
    assert cars[0].line == 2


def test_sample_engines_read_cleanly(samples_dir):
    engines, problems = read_engines(samples_dir / "engines.csv")
    assert problems == []
    assert len(engines) == 19
    assert engines[0].pool == v.POOL_MANIFEST  # "manifest" in the file
    no_model = [e for e in engines if e.model is None]
    assert [e.label for e in no_model] == ["BNSF 2310"]


# --- tidying up what was typed ----------------------------------------------------------


def test_capitals_and_spaces_are_forgiven(tmp_path):
    path = write(
        tmp_path,
        "cars.csv",
        " Mark , NUMBER,type ,Location\n"
        "csxt, 14420 ,  covered   hopper ,  west   STAGING \n",
    )
    (car,), problems = read_cars(path)
    assert problems == []
    assert (car.mark, car.number, car.type, car.location) == (
        "CSXT",
        "14420",
        "covered hopper",
        "West staging",
    )


def test_columns_can_come_in_any_order(tmp_path):
    path = write(tmp_path, "cars.csv", "location,type,number,mark\nWest staging,boxcar,1,UP\n")
    (car,), problems = read_cars(path)
    assert problems == [] and car.label == "UP 1"


def test_blank_lines_are_skipped_and_line_numbers_stay_true(tmp_path):
    path = write(
        tmp_path,
        "cars.csv",
        "mark,number,type,location\n\nUP,1,boxcar,West staging\n,,,\nUP,2,boxcar,Nowhere\n",
    )
    cars, problems = read_cars(path)
    assert [c.line for c in cars] == [3]
    assert problems == [
        "cars.csv, line 5: location is 'Nowhere' — expected East staging or West staging"
    ]


def test_byte_order_mark_from_excel_is_fine(tmp_path):
    path = write(
        tmp_path, "cars.csv", "mark,number,type,location\nUP,1,boxcar,West staging\n", "utf-8-sig"
    )
    cars, problems = read_cars(path)
    assert problems == [] and len(cars) == 1


# --- problems ---------------------------------------------------------------------------


def test_duplicate_car_points_at_the_first_one(tmp_path):
    path = write(
        tmp_path,
        "cars.csv",
        "mark,number,type,location\nUP,1,boxcar,West staging\nup,1,boxcar,East staging\n",
    )
    cars, problems = read_cars(path)
    assert len(cars) == 1
    assert problems == ["cars.csv, line 3: UP 1 is already on line 2"]


def test_missing_column(tmp_path):
    path = write(tmp_path, "cars.csv", "mark,number,location\nUP,1,West staging\n")
    assert read_cars(path) == (
        [],
        ["cars.csv: missing column type — the first line must be mark,number,type,location"],
    )


def test_unknown_and_doubled_columns(tmp_path):
    path = write(tmp_path, "cars.csv", "mark,number,type,location,colour,mark\n")
    _, problems = read_cars(path)
    assert problems == ["cars.csv: unknown column 'colour'", "cars.csv: column 'mark' appears twice"]


def test_wrong_number_of_values(tmp_path):
    path = write(tmp_path, "cars.csv", "mark,number,type,location\nUP,1,boxcar\n")
    assert read_cars(path)[1] == [
        "cars.csv, line 2: has 3 values, expected 4 (mark,number,type,location)"
    ]


def test_empty_required_values(tmp_path):
    path = write(tmp_path, "cars.csv", "mark,number,type,location\n,1,,West staging\n")
    assert read_cars(path)[1] == ["cars.csv, line 2: mark and type are empty"]


def test_engine_model_may_be_empty_but_pool_may_not(tmp_path):
    path = write(
        tmp_path,
        "engines.csv",
        "mark,number,model,pool,location\nUP,1,,Local,Storage\nUP,2,SD40-2,,Storage\n",
    )
    engines, problems = read_engines(path)
    assert [e.label for e in engines] == ["UP 1"]
    assert problems == ["engines.csv, line 3: pool is empty"]


def test_bad_engine_pool_and_location_both_reported(tmp_path):
    path = write(
        tmp_path, "engines.csv", "mark,number,model,pool,location\nUP,1,SD40-2,road,Shop\n"
    )
    assert read_engines(path)[1] == [
        "engines.csv, line 2: pool is 'road' — expected Local, Switcher or Manifest",
        "engines.csv, line 2: location is 'Shop' — expected Storage, East staging or West staging",
    ]


def test_engines_cannot_be_on_yard_tracks(tmp_path):
    path = write(
        tmp_path, "engines.csv", "mark,number,model,pool,location\nUP,1,,Local,Locals track\n"
    )
    assert "location is 'Locals track'" in read_engines(path)[1][0]


def test_missing_and_empty_files(tmp_path):
    assert read_cars(tmp_path / "cars.csv")[1][0].startswith("cars.csv: file not found")
    assert read_cars(write(tmp_path, "cars.csv", "\n\n"))[1] == ["cars.csv: the file is empty"]


def test_file_saved_in_old_windows_encoding(tmp_path):
    path = tmp_path / "cars.csv"
    path.write_bytes("mark,number,type,location\nUP,1,boîte,West staging\n".encode("cp1252"))
    assert "save the file as 'CSV UTF-8'" in read_cars(path)[1][0]


# --- engine counts --------------------------------------------------------------------------


def test_enough_engines():
    pools = [v.POOL_SWITCHER] + [v.POOL_LOCAL] * 2 + [v.POOL_MANIFEST] * 6
    assert engine_count_problems(pools) == []


def test_too_few_engines():
    pools = [v.POOL_LOCAL] + [v.POOL_MANIFEST] * 5
    assert engine_count_problems(pools) == [
        "engines.csv: needs at least 1 switcher engine (the yard switcher); found 0",
        "engines.csv: needs at least 2 local engines (the local runs with 2); found 1",
        "engines.csv: needs at least 6 manifest engines (both manifests can need 3 each); found 5",
    ]
