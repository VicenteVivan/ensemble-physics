# Experiment 2

Section 1 combines ensemble mass discrimination with change localization
(55 ordinary trials and five catches). Section 2 asks whether a highlighted
marble became lighter, stayed the same or became heavier (60 trials).
The folder includes all 236 stimulus videos, their parameters and two tutorial videos.

Tested with Python 3.10.21 and the pinned requirements. From this folder:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PORT=5001 python experiment.py
```

Open `http://127.0.0.1:5001/?PROLIFIC_PID=debug&STUDY_ID=debug&SESSION_ID=debug`.
Completed responses are saved locally to `results/responses.jsonl`. Optional
MongoDB settings are listed in `.env.example`; no database is needed to run locally.
Use a single server process because active sessions are stored in memory.
