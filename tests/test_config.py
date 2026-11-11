"""Step 2: config loading and checking."""

import copy
import textwrap

import pytest

from trainops import vocab
from trainops.config import ConfigError, load_config, parse_config


def base_config():
    """A small valid configuration: one fixed incoming, one fixed outgoing, one random spot."""
    return {
        "settings": {
            "hold_days_on_locals": 2,
            "eastbound_length_min": 12,
            "eastbound_length_max": 20,
            "train_nominal_max": 20,
            "three_engines_from": 16,
            "capacity": {"east_staging": 30, "west_staging": 70, "yard_track": 35},
        },
        "industries": [
            {
                "id": "industry_1",
                "name": "Industry #1",
                "spots": [
                    {
                        "spot_id": "industry_1_door_1",
                        "name": "Loading door 1",
                        "requirement_mode": "fixed",
                        "car_type": "tank car",
                        "direction": "incoming",
                        "source": "East",
                        "base_processing_days": 3,
                        "delay_chance": 0.1,
                        "cooldown_days": 0,
                    },
                    {
                        "spot_id": "industry_1_door_2",
                        "name": "Loading door 2",
                        "requirement_mode": "fixed",
                        "car_type": "boxcar",
                        "direction": "outgoing",
                        "pattern": ["East", "East", "West"],
                        "disruption_chance": 0.1,
                        "base_processing_days": 2,
                        "delay_chance": 0.1,
                        "cooldown_days": 1,
                    },
                ],
            },
            {
                "id": "transfer",
                "name": "Transfer Facility",
                "spots": [
                    {
                        "spot_id": "transfer_track_2",
                        "name": "Team track 2",
                        "requirement_mode": "random",
                        "possible_requirements": [
                            {
                                "car_type": "boxcar",
                                "direction": "incoming",
                                "source_weights": {"East": 0.5, "West": 0.5},
                                "weight": 3,
                                "base_processing_days": 2,
                                "delay_chance": 0.1,
                                "cooldown_days": 0,
                            },
                            {
                                "car_type": "covered hopper",
                                "direction": "outgoing",
                                "destination_weights": {"East": 0.3, "West": 0.7},
                                "weight": 1,
                                "base_processing_days": 3,
                            },
                        ],
                    }
                ],
            },
        ],
    }


def door_2(cfg):
    return cfg["industries"][0]["spots"][1]


def door_1(cfg):
    return cfg["industries"][0]["spots"][0]


def random_spot(cfg):
    return cfg["industries"][1]["spots"][0]


def problems_of(cfg):
    with pytest.raises(ConfigError) as info:
        parse_config(cfg)
    return info.value.problems


def only_problem(cfg):
    problems = problems_of(cfg)
    assert len(problems) == 1, problems
    return problems[0]


# --- good configurations ---------------------------------------------------


def test_sample_config_passes_all_checks(samples_dir):
    config = load_config(samples_dir / "config.yaml")
    assert [i.name for i in config.industries] == [
        "Northfield Paper",
        "Harbor Feed Mill",
        "Transfer Facility",
    ]
    assert len(config.spots) == 7
    assert config.settings.capacity.west_staging == 70


def test_base_config_parses_into_typed_values():
    config = parse_config(base_config())
    assert config.settings.eastbound_length_max == 20

    incoming = config.spot("industry_1_door_1")
    assert incoming.label == "Industry #1, Loading door 1"
    assert incoming.fixed.source == "East"
    assert incoming.fixed.pattern == ()

    outgoing = config.spot("industry_1_door_2")
    assert outgoing.fixed.pattern == ("East", "East", "West")
    assert outgoing.fixed.source is None

    rnd = config.spot("transfer_track_2")
    assert rnd.fixed is None
    first, second = rnd.possible_requirements
    assert first.side_weights == {"East": 0.5, "West": 0.5}
    assert first.weight == 3.0
    assert second.side_weights == {"East": 0.3, "West": 0.7}


def test_words_match_regardless_of_capitals_and_spaces():
    cfg = base_config()
    door_1(cfg).update(requirement_mode="FIXED", direction="Incoming", source="  east ")
    door_2(cfg).update(direction="OUTGOING", pattern=["east", "WEST", "East"])
    random_spot(cfg)["requirement_mode"] = "Random"
    random_spot(cfg)["possible_requirements"][0]["source_weights"] = {"west": 1}
    config = parse_config(cfg)

    assert config.spot("industry_1_door_1").requirement_mode == vocab.FIXED
    assert config.spot("industry_1_door_1").fixed.direction == vocab.INCOMING
    assert config.spot("industry_1_door_1").fixed.source == "East"
    assert config.spot("industry_1_door_2").fixed.pattern == ("East", "West", "East")
    weights = config.spot("transfer_track_2").possible_requirements[0].side_weights
    assert weights == {"East": 0.0, "West": 1.0}


def test_optional_fields_take_defaults():
    cfg = base_config()
    for key in ("disruption_chance", "delay_chance", "cooldown_days"):
        del door_2(cfg)[key]
    del random_spot(cfg)["possible_requirements"][0]["weight"]
    config = parse_config(cfg)
    fixed = config.spot("industry_1_door_2").fixed
    assert (fixed.disruption_chance, fixed.delay_chance, fixed.cooldown_days) == (0.0, 0.0, 0)
    assert config.spot("transfer_track_2").possible_requirements[0].weight == 1.0


def test_missing_settings_use_defaults():
    cfg = base_config()
    del cfg["settings"]
    settings = parse_config(cfg).settings
    assert settings.hold_days_on_locals == 2
    assert settings.eastbound_length_min == 12
    assert settings.eastbound_length_max == 20
    assert settings.train_nominal_max == 20
    assert settings.three_engines_from == 16
    assert settings.capacity.east_staging == 30
    assert settings.capacity.west_staging == 70
    assert settings.capacity.yard_track == 35


def test_partial_settings_keep_other_defaults():
    cfg = base_config()
    cfg["settings"] = {"hold_days_on_locals": 0, "capacity": {"yard_track": 32}}
    settings = parse_config(cfg).settings
    assert settings.hold_days_on_locals == 0
    assert settings.capacity.yard_track == 32
    assert settings.capacity.east_staging == 30


def test_text_values_have_extra_spaces_collapsed():
    cfg = base_config()
    door_1(cfg)["name"] = "  Chemical   unloading "
    door_1(cfg)["car_type"] = "tank  car"
    spot = parse_config(cfg).spot("industry_1_door_1")
    assert spot.name == "Chemical unloading"
    assert spot.fixed.car_type == "tank car"


# --- the spec's example message ---------------------------------------------


def test_bad_pattern_word_gives_spec_example_message():
    cfg = base_config()
    door_2(cfg)["pattern"] = ["East", "Eest"]
    assert only_problem(cfg) == (
        "Industry #1, Loading door 2: pattern contains 'Eest' — expected East or West"
    )


# --- settings problems --------------------------------------------------------


def test_misspelled_setting_suggests_the_right_name():
    cfg = base_config()
    cfg["settings"]["hold_day_on_locals"] = 3
    assert only_problem(cfg) == (
        "Settings: unknown field 'hold_day_on_locals' (did you mean 'hold_days_on_locals'?)"
    )


@pytest.mark.parametrize("value", ["two", 2.5, -1, True, None])
def test_setting_must_be_a_whole_number(value):
    cfg = base_config()
    cfg["settings"]["eastbound_length_min"] = value
    if value is None:  # left blank: falls back to the default
        assert parse_config(cfg).settings.eastbound_length_min == 12
        return
    assert "'eastbound_length_min' must be a whole number of 1 or more" in only_problem(cfg)


def test_capacity_must_be_at_least_one():
    cfg = base_config()
    cfg["settings"]["capacity"]["yard_track"] = 0
    assert only_problem(cfg) == (
        "Settings, capacity: 'yard_track' must be a whole number of 1 or more (found 0)"
    )


def test_eastbound_min_above_max_is_refused():
    cfg = base_config()
    cfg["settings"]["eastbound_length_min"] = 21
    assert only_problem(cfg) == (
        "Settings: eastbound_length_min (21) is larger than eastbound_length_max (20)"
    )


def test_eastbound_max_must_fit_east_staging():
    cfg = base_config()
    cfg["settings"]["eastbound_length_max"] = 31
    assert "would not fit in East staging" in only_problem(cfg)


# --- spot problems ------------------------------------------------------------


def test_wrong_word_names_the_choices():
    cfg = base_config()
    door_1(cfg)["direction"] = "incomming"
    assert only_problem(cfg) == (
        "Industry #1, Loading door 1: 'direction' is 'incomming' — expected incoming or outgoing"
    )


def test_missing_required_field():
    cfg = base_config()
    del door_1(cfg)["base_processing_days"]
    assert only_problem(cfg) == "Industry #1, Loading door 1: missing 'base_processing_days'"


def test_position_in_config_is_refused():
    cfg = base_config()
    door_2(cfg)["position"] = 0
    assert "'position' is kept by the program" in only_problem(cfg)


def test_misspelled_spot_field_suggests_the_right_name():
    cfg = base_config()
    door_2(cfg)["cooldown_day"] = 1
    assert only_problem(cfg) == (
        "Industry #1, Loading door 2: unknown field 'cooldown_day' (did you mean 'cooldown_days'?)"
    )


def test_incoming_spot_with_pattern_is_refused():
    cfg = base_config()
    door_1(cfg)["pattern"] = ["East"]
    assert only_problem(cfg) == (
        "Industry #1, Loading door 1: 'pattern' only applies to outgoing spots"
    )


def test_outgoing_spot_with_source_is_refused():
    cfg = base_config()
    door_2(cfg)["source"] = "West"
    assert only_problem(cfg) == (
        "Industry #1, Loading door 2: 'source' only applies to incoming spots"
    )


def test_outgoing_spot_needs_a_pattern_list():
    cfg = base_config()
    door_2(cfg)["pattern"] = "East"
    assert "'pattern' must be a list" in only_problem(cfg)
    del door_2(cfg)["pattern"]
    assert "missing 'pattern'" in only_problem(cfg)


def test_delay_chance_of_one_is_refused_but_disruption_of_one_is_allowed():
    cfg = base_config()
    door_2(cfg)["disruption_chance"] = 1
    parse_config(cfg)
    door_2(cfg)["delay_chance"] = 1
    assert "'delay_chance' must be a number from 0 up to (but not including) 1" in only_problem(
        cfg
    )


def test_chance_above_one_is_refused():
    cfg = base_config()
    door_2(cfg)["disruption_chance"] = 1.5
    assert only_problem(cfg) == (
        "Industry #1, Loading door 2: 'disruption_chance' must be a number from 0 to 1 (found 1.5)"
    )


def test_processing_days_must_be_at_least_one():
    cfg = base_config()
    door_1(cfg)["base_processing_days"] = 0
    assert "'base_processing_days' must be a whole number of 1 or more (found 0)" in only_problem(
        cfg
    )


def test_fixed_spot_with_possible_requirements_is_refused():
    cfg = base_config()
    door_1(cfg)["possible_requirements"] = []
    assert only_problem(cfg) == (
        "Industry #1, Loading door 1: 'possible_requirements' only applies to random spots"
    )


def test_random_spot_with_fixed_fields_is_refused():
    cfg = base_config()
    random_spot(cfg)["car_type"] = "boxcar"
    assert only_problem(cfg) == (
        "Transfer Facility, Team track 2: 'car_type' belongs inside each possible "
        "requirement of a random spot"
    )


def test_random_spot_needs_requirements():
    cfg = base_config()
    random_spot(cfg)["possible_requirements"] = []
    assert "'possible_requirements' must list at least one requirement" in only_problem(cfg)


def test_random_requirement_problems_name_the_requirement():
    cfg = base_config()
    random_spot(cfg)["possible_requirements"][1]["destination_weights"] = {"Eest": 1}
    assert only_problem(cfg) == (
        "Transfer Facility, Team track 2, possible requirement 2: "
        "'destination_weights' has 'Eest' — expected East or West"
    )


def test_random_requirement_uses_the_weights_for_its_direction():
    cfg = base_config()
    req = random_spot(cfg)["possible_requirements"][1]
    req["source_weights"] = req.pop("destination_weights")
    problems = problems_of(cfg)
    assert any("'source_weights' only applies to incoming requirements" in p for p in problems)
    assert any("missing 'destination_weights'" in p for p in problems)


def test_weights_all_zero_are_refused():
    cfg = base_config()
    random_spot(cfg)["possible_requirements"][0]["source_weights"] = {"East": 0, "West": 0}
    assert "needs at least one weight above 0" in only_problem(cfg)


def test_same_side_twice_in_weights_is_refused():
    cfg = base_config()
    random_spot(cfg)["possible_requirements"][0]["source_weights"] = {"East": 1, "east": 2}
    assert "'source_weights' lists East twice" in only_problem(cfg)


def test_requirement_weight_must_be_above_zero():
    cfg = base_config()
    random_spot(cfg)["possible_requirements"][0]["weight"] = 0
    assert "'weight' must be a number above 0 (found 0)" in only_problem(cfg)


# --- names and ids ---------------------------------------------------------------


def test_spot_ids_must_be_unique_across_industries():
    cfg = base_config()
    random_spot(cfg)["spot_id"] = "INDUSTRY_1_door_1"
    assert only_problem(cfg) == (
        "Transfer Facility, Team track 2: spot_id 'INDUSTRY_1_door_1' is already used by "
        "Industry #1, Loading door 1"
    )


def test_spot_names_must_be_unique_within_an_industry():
    cfg = base_config()
    door_2(cfg)["name"] = "loading door 1"
    assert "another spot in this industry already has this name" in only_problem(cfg)


def test_same_spot_name_in_different_industries_is_fine():
    cfg = base_config()
    random_spot(cfg)["name"] = "Loading door 1"
    parse_config(cfg)


def test_industry_ids_and_names_must_be_unique():
    cfg = base_config()
    second = copy.deepcopy(cfg["industries"][1])
    second["spots"][0]["spot_id"] = "other_spot"
    cfg["industries"].append(second)
    assert "already used by Transfer Facility" in only_problem(cfg)

    second["id"] = "transfer_2"
    assert "another industry already has this name" in only_problem(cfg)


def test_no_industries_is_refused():
    cfg = base_config()
    cfg["industries"] = []
    assert only_problem(cfg) == "Configuration: 'industries' must list at least one industry"


def test_spot_without_name_is_labelled_by_position():
    cfg = base_config()
    del door_1(cfg)["name"]
    del door_1(cfg)["spot_id"]
    problems = problems_of(cfg)
    assert "Industry #1, spot 1 in the list: missing 'spot_id'" in problems
    assert "Industry #1, spot 1 in the list: missing 'name'" in problems


def test_every_problem_is_reported_at_once():
    cfg = base_config()
    cfg["settings"]["train_nominal_max"] = "twenty"
    door_1(cfg)["source"] = "North"
    door_2(cfg)["pattern"] = ["Eest", "Wset"]
    problems = problems_of(cfg)
    assert len(problems) == 4
    message = str(ConfigError(problems))
    assert message.startswith("The configuration has 4 problems:")


# --- reading the file ------------------------------------------------------------


def write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


MINIMAL_YAML = """\
    industries:
      - id: mill
        name: Mill
        spots:
          - spot_id: mill_pit
            name: Pit
            requirement_mode: fixed
            car_type: covered hopper
            direction: incoming
            source: West
            base_processing_days: 1
"""


def test_minimal_file_loads(tmp_path):
    config = load_config(write(tmp_path, MINIMAL_YAML))
    assert config.spot("mill_pit").label == "Mill, Pit"


def test_file_with_byte_order_mark_loads(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(MINIMAL_YAML), encoding="utf-8-sig")
    load_config(path)


def test_field_written_twice_is_refused_with_line_number(tmp_path):
    text = MINIMAL_YAML + "            base_processing_days: 2\n"
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, text))
    assert info.value.problems == [
        "config.yaml, line 12: 'base_processing_days' appears twice in the same section"
    ]


def test_broken_yaml_is_reported_with_line_number(tmp_path):
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, "industries:\n  - id: mill\n   name: Mill\n"))
    (problem,) = info.value.problems
    assert problem.startswith("config.yaml, line 3: the file isn't valid YAML")


def test_empty_file_is_refused(tmp_path):
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, ""))
    assert info.value.problems == ["config.yaml: the file is empty"]


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(ConfigError) as info:
        load_config(tmp_path / "nope.yaml")
    assert info.value.problems[0].startswith("configuration file not found:")
