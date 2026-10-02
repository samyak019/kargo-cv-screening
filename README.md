# Kargo PM / SPM CV screening

Spec: `kargo_pm_spm_rubric.txt`. The model (`claude-sonnet-5`) scores each CV against the PM and SPM criteria, 0–4 per criterion, and has to quote the CV for every point. Code then checks each quote against the CV text and drops any that don't match or are only credentials. The weighted score, gate G1, rescue rules R1–R4, flags F1–F2 and the band (Advance / Review / Reject) are all computed in `rubric.py`, never by the model. Emails and phone numbers are stripped from a CV before it is sent.

## Web app (Vercel)

Open the site, then click **+ Add CVs** or drop .pdf / .docx files on the page. The site is open: anyone with the link can view candidates and add CVs. Each CV takes about a minute and is scored for both roles. Uploading a CV that has already been scored does nothing, so it is never charged twice. Click a candidate to see the evidence, or to remove them.

It needs these environment variables in the Vercel project (Settings → Environment Variables), then a redeploy:

| Variable | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (required) |
| `BLOB_READ_WRITE_TOKEN` | Added automatically when the Blob store is connected |
| `ACCESS_CODE` | Optional. Set it to require a passphrase for every view and upload. |

Scored results are stored in Vercel Blob as `candidates/<id>-<random>.json`. The raw CV file is not stored. Blob objects are public-read at unguessable URLs, and the app serves them through its API.

## Command line

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=...
.venv/bin/python screen.py                 # scores new or changed CVs in ./cvs, keeps earlier results
.venv/bin/python screen.py --rescore       # re-score everything
.venv/bin/python screen.py --roles SPM     # one role
.venv/bin/python screen.py --calibrate     # needs ratings.csv (see ratings.example.csv)
.venv/bin/python report.py                 # rebuild report.html from the last run
.venv/bin/python -m pytest -q              # offline tests
KARGO_LIVE=1 .venv/bin/python -m pytest -q -k live   # real API calls against the 8 calibration CVs
```

Outputs: `report.html` (open this one), `results.csv` (one row per candidate per role), `evidence.json` (kept and dropped quotes, and the facts behind each rule). None of them are committed.

## Files

- `rubric.py`: weights, rules and routing. Pure code.
- `screen.py`: text extraction, redaction, the model call, quote checks, the CLI and calibrate mode.
- `report.py`: the HTML report and the web page. `python report.py --app public/index.html` regenerates the page after you edit the template.
- `webapp.py`, `webhttp.py`, `api/`: the Vercel functions.
- `tests/`: `calibration_profiles.py` holds the Section 6 numbers.
