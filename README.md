# Flux demo

An offline, fixture-driven demo that compares two illustrative 300 MW firm-generation additions on a small synthetic grid under a fixed cold-weather stress scenario.

The model is intentionally synthetic. It is not a Texas-grid reconstruction, outage forecast, interconnection study, or licensing assessment.

## Run locally

1. Generate (or refresh) the deterministic demo bundle:

   ```powershell
   python model/generate_demo.py
   ```

2. Install the UI dependencies and start the local demo:

   ```powershell
   npm --prefix web install
   npm --prefix web run dev
   ```

3. Open the local URL printed by Vite. For an offline rehearsal, first run `npm --prefix web run build`, then `npm --prefix web run preview`.

## Five-minute walkthrough

1. Start on **Baseline** and call out the fixed stress assumptions and modeled shedding.
2. Select **Candidate A** and compare the signed reduction in shed MW/MWh.
3. Select **Candidate B**, then use the loading view toggle to inspect the synthetic branch loading layer.
4. Open **Sources & limits**. State that all inputs are synthetic and that the result is illustrative.
5. Close with the next validation: replace the fixture with a supported synthetic or approved study case before making any real-world claim.

## Verification

```powershell
python -m unittest discover -s model -p "test_*.py"
npm --prefix web run build
```

`R08` (tunnel/origin discovery) and `D01` (case acquisition) are deliberately not performed. The model uses a checked-in synthetic fixture until those inputs are available.
