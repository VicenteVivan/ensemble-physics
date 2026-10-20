# Experiment 1

Two counterbalanced blocks compare single-marble and ensemble mass judgments.
Each block has 57 adaptive trials and three catch trials, preceded by practice.
The folder includes 441 single-marble videos, 78 ensemble videos and two tutorial GIFs.

Tested with Python 3.10.21 and the pinned requirements. From this folder:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python experiment.py
```

Open `http://127.0.0.1:5000/?PROLIFIC_PID=debug&STUDY_ID=debug&SESSION_ID=debug`.
Completed responses are saved locally to `results/responses.jsonl`. Optional
MongoDB settings are listed in `.env.example`; no database is needed to run locally.
