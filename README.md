# Ensemble Physics: Paper Materials

Data, analysis code and materials for the paper.

- `code/`: models, summaries, figure scripts and requirements for each experiment.
- `data/`: anonymous records, participant and trial inclusion tables, and a [codebook](data/codebook.md).
- `materials/`: experiment apps, videos, stimulus parameters and rendering scripts.
- `results/`: saved fits, summaries, figure PDFs and run settings.

## Reproduce the results

Download and extract the [complete v1.0 package](https://github.com/VicenteVivan/ensemble-physics/releases/download/v1.0/ensemble-physics-v1.0.zip),
which includes the saved fits and videos. The Git checkout contains the code, data
and smaller materials.

Use Python 3.12 with a separate environment for each experiment. From this folder:

```bash
python3.12 -m venv .venv-e1
.venv-e1/bin/python -m pip install -r code/experiment1/requirements.txt
.venv-e1/bin/python code/experiment1/run.py

python3.12 -m venv .venv-e2
.venv-e2/bin/python -m pip install -r code/experiment2/requirements.txt
.venv-e2/bin/python code/experiment2/run.py
```

On Windows, use `Scripts/python.exe` in place of `bin/python`.
The scripts read the saved fits and write to `results/experiment1/reproduced/`
and `results/experiment2/reproduced/`. Use `--out PATH` to select another folder.

| Output | Contents |
|---|---|
| Experiment 1: `summary.csv` | Parameters, widths and contrasts |
| Experiment 1: `participant_estimates.csv`, `curves.pdf` | Participant estimates and Figure 3 |
| Experiment 1: `glmm/` | GLMM estimates and comparisons |
| Experiment 2: `summary.csv`, `summary.json` | Accuracies, parameters, ensemble boost and correlations |
| Experiment 2: `participant_estimates.csv`, `figure5.pdf` | Participant estimates and Figure 5 |

The analyses use 100 participants in Experiment 1 and 80 in Experiment 2.
Participant and trial inclusion are specified in `data/`.
Lato is bundled; Figure 5 uses Arial when installed and Lato otherwise.

## Fit the models

From either experiment's code folder, using its environment:

```bash
python run.py --refit --seed 42
```

Fits are saved in new output folders. Fitting and plotting seeds default to 42.
Settings, package versions, diagnostic seeds and file hashes are recorded in
`provenance.json`.

To run the Experiment 1 GLMM, install R with `lme4` and `jsonlite`, then run:

```bash
python run.py --glmm --seed 42
```

Use `--rscript PATH` if Rscript is not on your PATH.

R versions: R 4.6.1, lme4 2.0.6, Matrix 1.7-5 and jsonlite 2.0.0.

## Materials

App launch instructions are in `materials/experiments/experiment1/README.md`
and `materials/experiments/experiment2/README.md`. The apps use Python 3.10.
See `materials/stimuli/README.md` for rendering instructions.

## License

Author-owned code, data and materials are released under [CC0](LICENSE).
Lato is included under the SIL Open Font License in each analysis's `fonts/` folder.
The [environment map](https://polyhaven.com/a/kiara_1_dawn) and
[textures](https://3dtextures.me/about/) are CC0.
Third-party software retains its own licenses.
