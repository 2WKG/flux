"""Canonical DuckDB DDL for the Flux fixture contract.

This module deliberately contains declarations only. Fixture data, additive
retrieval/line-detail tables, and initializer lifecycle behaviour belong to
their respective pipeline issues.
"""

CONTRACT_TABLES = (
    "counties",
    "buses",
    "lines",
    "gens",
    "loads",
    "critical_loads",
    "eaglei_outages",
    "weather_hourly",
    "storm_events",
    "hazard_static",
    "ba_load_hourly",
    "site_candidates",
    "scenarios",
    "outage_predictions",
    "cascade_runs",
    "site_scores",
    "line_upgrade_scores",
)

# All fixture and derived artifact rows identify both their input and the
# reproducible fixture build that wrote them. NULL remains the contract's only
# unavailable marker for the two optional source fields.
PROVENANCE_COLUMNS = """
    source_name TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_version TEXT,
    source_retrieved_at TIMESTAMP,
    fixture_batch_id TEXT NOT NULL
"""


SCHEMA_STATEMENTS = (
    f"""CREATE TABLE IF NOT EXISTS counties (
        county_fips TEXT PRIMARY KEY
            CHECK (regexp_full_match(county_fips, '[0-9]{{5}}')),
        name TEXT NOT NULL,
        state TEXT NOT NULL,
        pop BIGINT NOT NULL CHECK (pop >= 0),
        geom_wkb BLOB NOT NULL,
        {PROVENANCE_COLUMNS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS buses (
        bus_id BIGINT PRIMARY KEY,
        name TEXT NOT NULL,
        base_kv DOUBLE NOT NULL CHECK (isfinite(base_kv) AND base_kv > 0),
        lon DOUBLE NOT NULL CHECK (isfinite(lon) AND lon BETWEEN -180 AND 180),
        lat DOUBLE NOT NULL CHECK (isfinite(lat) AND lat BETWEEN -90 AND 90),
        county_fips TEXT REFERENCES counties(county_fips),
        ba_code TEXT,
        coord_source TEXT NOT NULL,
        zone INTEGER,
        area INTEGER,
        {PROVENANCE_COLUMNS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS lines (
        line_id BIGINT PRIMARY KEY,
        from_bus BIGINT NOT NULL REFERENCES buses(bus_id),
        to_bus BIGINT NOT NULL REFERENCES buses(bus_id),
        circuit TEXT NOT NULL,
        base_kv DOUBLE NOT NULL CHECK (isfinite(base_kv) AND base_kv > 0),
        r_pu DOUBLE NOT NULL CHECK (isfinite(r_pu)),
        x_pu DOUBLE NOT NULL CHECK (isfinite(x_pu)),
        rate_a_mw DOUBLE CHECK (rate_a_mw IS NULL OR (isfinite(rate_a_mw) AND rate_a_mw >= 0)),
        length_km DOUBLE NOT NULL CHECK (isfinite(length_km) AND length_km >= 0),
        geom_wkb BLOB,
        is_transformer BOOLEAN NOT NULL,
        {PROVENANCE_COLUMNS},
        UNIQUE (from_bus, to_bus, circuit)
    )""",
    f"""CREATE TABLE IF NOT EXISTS gens (
        gen_id BIGINT PRIMARY KEY,
        bus_id BIGINT NOT NULL REFERENCES buses(bus_id),
        fuel TEXT NOT NULL,
        pmax_mw DOUBLE NOT NULL CHECK (isfinite(pmax_mw) AND pmax_mw >= 0),
        eia_plant_id BIGINT,
        source_unit_id TEXT NOT NULL,
        {PROVENANCE_COLUMNS},
        UNIQUE (bus_id, source_unit_id)
    )""",
    f"""CREATE TABLE IF NOT EXISTS loads (
        load_id BIGINT PRIMARY KEY,
        bus_id BIGINT NOT NULL REFERENCES buses(bus_id),
        p_mw_nominal DOUBLE NOT NULL CHECK (isfinite(p_mw_nominal) AND p_mw_nominal >= 0),
        {PROVENANCE_COLUMNS},
        UNIQUE (bus_id)
    )""",
    f"""CREATE TABLE IF NOT EXISTS critical_loads (
        cl_id BIGINT PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('dod', 'hospital', 'water')),
        name TEXT NOT NULL,
        lon DOUBLE NOT NULL CHECK (isfinite(lon) AND lon BETWEEN -180 AND 180),
        lat DOUBLE NOT NULL CHECK (isfinite(lat) AND lat BETWEEN -90 AND 90),
        bus_id BIGINT REFERENCES buses(bus_id),
        county_fips TEXT NOT NULL REFERENCES counties(county_fips),
        {PROVENANCE_COLUMNS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS eaglei_outages (
        county_fips TEXT NOT NULL REFERENCES counties(county_fips),
        ts TIMESTAMP NOT NULL,
        customers_out BIGINT NOT NULL CHECK (customers_out >= 0),
        {PROVENANCE_COLUMNS},
        PRIMARY KEY (county_fips, ts)
    )""",
    f"""CREATE TABLE IF NOT EXISTS weather_hourly (
        county_fips TEXT NOT NULL REFERENCES counties(county_fips),
        ts TIMESTAMP NOT NULL,
        wind_ms DOUBLE CHECK (wind_ms IS NULL OR isfinite(wind_ms)),
        gust_ms DOUBLE CHECK (gust_ms IS NULL OR isfinite(gust_ms)),
        temp_c DOUBLE CHECK (temp_c IS NULL OR isfinite(temp_c)),
        ice_mm DOUBLE CHECK (ice_mm IS NULL OR (isfinite(ice_mm) AND ice_mm >= 0)),
        precip_mm DOUBLE CHECK (precip_mm IS NULL OR (isfinite(precip_mm) AND precip_mm >= 0)),
        {PROVENANCE_COLUMNS},
        PRIMARY KEY (county_fips, ts)
    )""",
    f"""CREATE TABLE IF NOT EXISTS storm_events (
        event_id BIGINT NOT NULL,
        county_fips TEXT NOT NULL REFERENCES counties(county_fips),
        ts_begin TIMESTAMP NOT NULL,
        ts_end TIMESTAMP NOT NULL CHECK (ts_end >= ts_begin),
        type TEXT NOT NULL,
        magnitude DOUBLE CHECK (magnitude IS NULL OR isfinite(magnitude)),
        {PROVENANCE_COLUMNS},
        PRIMARY KEY (event_id, county_fips)
    )""",
    f"""CREATE TABLE IF NOT EXISTS hazard_static (
        county_fips TEXT PRIMARY KEY REFERENCES counties(county_fips),
        nri_score DOUBLE CHECK (nri_score IS NULL OR isfinite(nri_score)),
        wildfire_hazard DOUBLE CHECK (wildfire_hazard IS NULL OR isfinite(wildfire_hazard)),
        seismic_pga DOUBLE CHECK (seismic_pga IS NULL OR (isfinite(seismic_pga) AND seismic_pga >= 0)),
        {PROVENANCE_COLUMNS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS ba_load_hourly (
        ba_code TEXT NOT NULL,
        ts TIMESTAMP NOT NULL,
        demand_mw DOUBLE NOT NULL CHECK (isfinite(demand_mw) AND demand_mw >= 0),
        {PROVENANCE_COLUMNS},
        PRIMARY KEY (ba_code, ts)
    )""",
    f"""CREATE TABLE IF NOT EXISTS site_candidates (
        site_id BIGINT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN (
            'coal_retired', 'coal_retiring', 'nuclear_existing', 'doe_federal', 'dod'
        )),
        lon DOUBLE NOT NULL CHECK (isfinite(lon) AND lon BETWEEN -180 AND 180),
        lat DOUBLE NOT NULL CHECK (isfinite(lat) AND lat BETWEEN -90 AND 90),
        county_fips TEXT NOT NULL REFERENCES counties(county_fips),
        bus_id BIGINT REFERENCES buses(bus_id),
        capacity_slot_mw DOUBLE NOT NULL CHECK (isfinite(capacity_slot_mw) AND capacity_slot_mw > 0),
        source_site_id TEXT NOT NULL,
        {PROVENANCE_COLUMNS},
        UNIQUE (source_name, source_site_id)
    )""",
    f"""CREATE TABLE IF NOT EXISTS scenarios (
        scenario_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('historical', 'forecast', 'synthetic')),
        ts_start TIMESTAMP NOT NULL,
        ts_end TIMESTAMP NOT NULL CHECK (ts_end >= ts_start),
        {PROVENANCE_COLUMNS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS outage_predictions (
        scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
        county_fips TEXT NOT NULL REFERENCES counties(county_fips),
        ts TIMESTAMP NOT NULL,
        p_out DOUBLE NOT NULL CHECK (isfinite(p_out) AND p_out BETWEEN 0 AND 1),
        customers_at_risk BIGINT NOT NULL CHECK (customers_at_risk >= 0),
        driver TEXT NOT NULL CHECK (driver IN ('ice', 'wind', 'heat', 'wildfire', 'flood', 'other')),
        {PROVENANCE_COLUMNS},
        PRIMARY KEY (scenario_id, county_fips, ts)
    )""",
    f"""CREATE TABLE IF NOT EXISTS cascade_runs (
        run_id TEXT NOT NULL,
        scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
        hour INTEGER NOT NULL CHECK (hour >= 0),
        tripped_element_ids_json JSON NOT NULL,
        lost_load_mw DOUBLE NOT NULL CHECK (isfinite(lost_load_mw) AND lost_load_mw >= 0),
        counties_dark_json JSON NOT NULL,
        critical_loads_lost_json JSON NOT NULL,
        counterfactual_site_id BIGINT REFERENCES site_candidates(site_id),
        {PROVENANCE_COLUMNS},
        PRIMARY KEY (run_id, hour)
    )""",
    f"""CREATE TABLE IF NOT EXISTS site_scores (
        site_id BIGINT NOT NULL REFERENCES site_candidates(site_id),
        scenario_id TEXT NOT NULL,
        unit_mw DOUBLE NOT NULL CHECK (isfinite(unit_mw) AND unit_mw > 0),
        safety_score DOUBLE NOT NULL CHECK (isfinite(safety_score) AND safety_score BETWEEN 0 AND 100),
        safety_flags_json JSON NOT NULL,
        grid_value_score DOUBLE CHECK (grid_value_score IS NULL OR (isfinite(grid_value_score) AND grid_value_score BETWEEN 0 AND 100)),
        lol_reduction_mwh DOUBLE CHECK (lol_reduction_mwh IS NULL OR isfinite(lol_reduction_mwh)),
        congestion_relief_pct DOUBLE CHECK (congestion_relief_pct IS NULL OR (isfinite(congestion_relief_pct) AND congestion_relief_pct BETWEEN 0 AND 100)),
        blackstart_reach_mw DOUBLE CHECK (blackstart_reach_mw IS NULL OR (isfinite(blackstart_reach_mw) AND blackstart_reach_mw >= 0)),
        {PROVENANCE_COLUMNS},
        PRIMARY KEY (site_id, scenario_id, unit_mw)
    )""",
    f"""CREATE TABLE IF NOT EXISTS line_upgrade_scores (
        line_id BIGINT PRIMARY KEY REFERENCES lines(line_id),
        congestion_usd_yr DOUBLE CHECK (congestion_usd_yr IS NULL OR isfinite(congestion_usd_yr)),
        dlr_uplift_mw DOUBLE CHECK (dlr_uplift_mw IS NULL OR isfinite(dlr_uplift_mw)),
        reconductor_uplift_mw DOUBLE CHECK (reconductor_uplift_mw IS NULL OR isfinite(reconductor_uplift_mw)),
        dlr_cost_usd DOUBLE CHECK (dlr_cost_usd IS NULL OR (isfinite(dlr_cost_usd) AND dlr_cost_usd >= 0)),
        reconductor_cost_usd DOUBLE CHECK (reconductor_cost_usd IS NULL OR (isfinite(reconductor_cost_usd) AND reconductor_cost_usd >= 0)),
        mw_per_musd DOUBLE CHECK (mw_per_musd IS NULL OR isfinite(mw_per_musd)),
        ferc_screen_pass BOOLEAN,
        spark_eligible BOOLEAN,
        {PROVENANCE_COLUMNS}
    )""",
    "CREATE INDEX IF NOT EXISTS idx_buses_county_fips ON buses (county_fips)",
    "CREATE INDEX IF NOT EXISTS idx_lines_endpoints ON lines (from_bus, to_bus)",
    "CREATE INDEX IF NOT EXISTS idx_gens_bus_id ON gens (bus_id)",
    "CREATE INDEX IF NOT EXISTS idx_loads_bus_id ON loads (bus_id)",
    "CREATE INDEX IF NOT EXISTS idx_critical_loads_county_fips ON critical_loads (county_fips)",
    "CREATE INDEX IF NOT EXISTS idx_eaglei_outages_ts ON eaglei_outages (ts)",
    "CREATE INDEX IF NOT EXISTS idx_weather_hourly_ts ON weather_hourly (ts)",
    "CREATE INDEX IF NOT EXISTS idx_storm_events_window ON storm_events (ts_begin, ts_end)",
    "CREATE INDEX IF NOT EXISTS idx_site_candidates_county_fips ON site_candidates (county_fips)",
    "CREATE INDEX IF NOT EXISTS idx_outage_predictions_scenario_ts ON outage_predictions (scenario_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_cascade_runs_scenario_id ON cascade_runs (scenario_id)",
    "CREATE INDEX IF NOT EXISTS idx_site_scores_scenario_id ON site_scores (scenario_id)",
)


# These tables extend the shared contract without changing its original table
# catalogue. They are kept separate so a later initializer can add them to an
# existing fixture database without rebuilding or truncating core artifacts.
ADDITIVE_TABLES = ("line_upgrade_detail", "corpus_chunks")


ADDITIVE_SCHEMA_STATEMENTS = (
    f"""CREATE TABLE IF NOT EXISTS line_upgrade_detail (
        line_id BIGINT PRIMARY KEY REFERENCES lines(line_id),
        owner TEXT,
        conductor_material TEXT,
        conductor_kcmil DOUBLE CHECK (conductor_kcmil IS NULL OR (isfinite(conductor_kcmil) AND conductor_kcmil > 0)),
        static_rating_mw DOUBLE NOT NULL CHECK (isfinite(static_rating_mw) AND static_rating_mw >= 0),
        aar_rating_mw DOUBLE CHECK (aar_rating_mw IS NULL OR (isfinite(aar_rating_mw) AND aar_rating_mw >= 0)),
        dlr_p50_mw DOUBLE CHECK (dlr_p50_mw IS NULL OR (isfinite(dlr_p50_mw) AND dlr_p50_mw >= 0)),
        dlr_hours_above_static INTEGER CHECK (dlr_hours_above_static IS NULL OR dlr_hours_above_static >= 0),
        best_tech TEXT CHECK (best_tech IS NULL OR best_tech IN ('dlr', 'reconductor')),
        payback_yr DOUBLE CHECK (payback_yr IS NULL OR (isfinite(payback_yr) AND payback_yr >= 0)),
        congestion_method TEXT NOT NULL CHECK (congestion_method IN ('exact', 'fuzzy', 'twin_proxy', 'unmapped')),
        region TEXT NOT NULL,
        {PROVENANCE_COLUMNS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS corpus_chunks (
        chunk_id TEXT PRIMARY KEY,
        doc TEXT NOT NULL,
        title TEXT NOT NULL,
        page INTEGER NOT NULL CHECK (page > 0),
        chunk_ordinal INTEGER NOT NULL CHECK (chunk_ordinal >= 0),
        text TEXT NOT NULL,
        embedding FLOAT[1024],
        {PROVENANCE_COLUMNS},
        UNIQUE (doc, page, chunk_ordinal)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_line_upgrade_detail_region ON line_upgrade_detail (region)",
    "CREATE INDEX IF NOT EXISTS idx_corpus_chunks_doc_page ON corpus_chunks (doc, page)",
)
