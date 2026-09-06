from pathlib import Path
from fastapi.testclient import TestClient
from copilot.app import create_app
from copilot.config import Settings

def client(tmp_path:Path): return TestClient(create_app(Settings(duckdb_path=tmp_path/'missing.duckdb')))
def test_prediction_missing_artifact_is_unavailable(tmp_path):
 r=client(tmp_path).get('/predictions'); assert r.status_code==503; assert r.json()['status']=='unavailable'
def test_cascade_aggregate_is_unavailable(tmp_path):
 r=client(tmp_path).get('/cascade',params={'scenario_id':'uri_2021'}); assert r.status_code==503; assert r.json()['status']=='unavailable'
def test_prediction_invalid_limit_is_rejected(tmp_path):
 r=client(tmp_path).get('/predictions',params={'limit':0}); assert r.status_code==422
