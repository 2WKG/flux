import pandas as pd

from pipelines.build import _dod_filename
from pipelines.eia860 import _scope_plants
from pipelines.storm_events import _scope_events, _zone_crosswalk


def test_minnesota_storm_event_and_zone_inputs_are_not_filtered_to_texas(tmp_path):
    crosswalk = tmp_path / "zones.txt"
    crosswalk.write_text("TX|001||| | |48001\nMN|002||| | |27001\n")
    events = pd.DataFrame({"STATE": ["TEXAS", "MINNESOTA"], "EVENT_ID": [1, 2]})

    assert _scope_events(events, "MN").EVENT_ID.tolist() == [2]
    assert _zone_crosswalk(crosswalk, "MN") == {"002": ["27001"]}


def test_minnesota_eia_plants_are_retained_by_scope():
    plants = pd.DataFrame({"state": ["TX", "MN"], "plant_id_eia": [1, 2]})
    assert _scope_plants(plants, "MN").plant_id_eia.tolist() == [2]


def test_builder_uses_scope_derived_dod_filename():
    assert _dod_filename("MN") == "mn.geojson"
    assert _dod_filename(["MN", "TX"]) == "mn-tx.geojson"
