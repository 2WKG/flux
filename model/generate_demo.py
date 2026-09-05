"""Create Flux's synthetic demo payload; replace this writer with ingestion later."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "demo" / "bundle.json"
DURATION_HOURS = 4
BUSES = [{"id":"west","name":"West Junction","x":120,"y":270},{"id":"north","name":"North Ridge","x":300,"y":115},{"id":"central","name":"Central Hub","x":405,"y":275},{"id":"east","name":"East Plain","x":650,"y":210},{"id":"south","name":"South Bend","x":510,"y":435}]
LINES = [{"id":a,"from":b,"to":c} for a,b,c in [("w-n","west","north"),("w-c","west","central"),("n-c","north","central"),("c-e","central","east"),("c-s","central","south"),("e-s","east","south")]]
CANDIDATES = [{"id":"a","name":"Candidate A","busId":"west","x":120,"y":270,"addedMw":300,"description":"Illustrative western addition near the import path."},{"id":"b","name":"Candidate B","busId":"east","x":650,"y":210,"addedMw":300,"description":"Illustrative eastern addition near demand."}]
VALUES = {"baseline":(188,1177,{"w-n":82,"w-c":94,"n-c":69,"c-e":96,"c-s":88,"e-s":74}),"a":(51,1437,{"w-n":61,"w-c":77,"n-c":59,"c-e":83,"c-s":70,"e-s":62}),"b":(82,1437,{"w-n":78,"w-c":89,"n-c":66,"c-e":75,"c-s":81,"e-s":57})}
def result_payload() -> dict:
    baseline=VALUES["baseline"][0]
    scenarios={key:{"label":"Baseline" if key=="baseline" else f"Candidate {key.upper()}","shedMw":shed,"shedMwh":shed*DURATION_HOURS,"availableGenerationMw":generation,"demandMw":1365,"improvementMw":baseline-shed,"lineLoadings":loads,"reasons":[] if key=="baseline" else ["Uses the same fixed stress and 300 MW capacity assumption.","The difference is caused by synthetic network placement, not a real interconnection claim."]} for key,(shed,generation,loads) in VALUES.items()}
    fixture={"buses":BUSES,"lines":LINES,"candidates":CANDIDATES}
    return {"schemaVersion":1,"generatedFrom":"checked-in synthetic fixture","fixtureHash":hashlib.sha256(json.dumps(fixture,sort_keys=True).encode()).hexdigest()[:12],"solverStatus":"Synthetic preview — ingestion-ready contract","stress":{"name":"Illustrative cold-weather stress","demandMultiplier":1.17,"generationAvailability":.79,"durationHours":DURATION_HOURS},"dataStatus":{"mode":"synthetic","next":"Replace data/demo/bundle.json through the ingestion pipeline."},"limitations":["Synthetic model; not the Texas grid or a real interconnection study.","Illustrative snapshot; not an outage forecast or historical reconstruction."],"sources":[{"label":"Current data","detail":"Five-bus synthetic fixture"},{"label":"Next data","detail":"Ingested network, scenario, and site datasets"}],"network":fixture,"scenarios":scenarios}
def main() -> None:
    OUTPUT.parent.mkdir(parents=True,exist_ok=True); OUTPUT.write_text(json.dumps(result_payload(),indent=2)+"\n",encoding="utf-8"); print(f"Wrote {OUTPUT.relative_to(ROOT)}")
if __name__ == "__main__": main()
