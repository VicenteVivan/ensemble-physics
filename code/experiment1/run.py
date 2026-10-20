"""Reproduce Experiment 1 results; optionally refit with seed 42."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(name, '1')
os.environ.setdefault('MPLBACKEND', 'Agg')

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / 'data/experiment1/data.json'
RESULTS = ROOT / 'results/experiment1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment():
    names = ('numpy', 'scipy', 'pymc', 'pytensor', 'arviz', 'xarray', 'pandas',
             'matplotlib', 'h5py', 'h5netcdf', 'seaborn')
    return dict(python=platform.python_version(), platform=platform.platform(),
                packages={n: importlib.metadata.version(n) for n in names},
                thread_limits={n: os.environ.get(n) for n in
                    ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS')})


def run_glmm(data, out, seed, rscript):
    rows = []
    for person in data:
        for condition in ('single', 'multi'):
            n = 0
            for key, trial in person[condition].items():
                if key == 'fit_details' or key.startswith('catch'):
                    continue
                if trial['prediction'] not in ('Heavier', 'Lighter') or trial['mass'] <= 0:
                    raise ValueError('Invalid response or mass')
                rows.append(dict(Subject=person['PROLIFIC_PID'], Type=condition,
                                 Mass=trial['mass'] / 8,
                                 Response=int(trial['prediction'] == 'Heavier'), Trial=key))
                n += 1
            if n != 57:
                raise ValueError('Expected 57 noncatch responses per condition')
    if len(rows) != 11400:
        raise ValueError('Expected 11400 noncatch responses')
    with (out / 'data.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    manifest = dict(seed=seed, participants=100, noncatch_trials=11400,
                    data_sha256=sha(DATA), code_sha256=sha(HERE / 'glmm.R'))
    with (out / 'run.log').open('w') as log:
        subprocess.run([rscript, str(HERE / 'glmm.R'), str(out), str(seed)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    result = json.loads((out / 'results.json').read_text())
    for item in result['diagnostics'].values():
        if (item['singular'] or item['hessian_min_eigenvalue'] <= 0 or
                item['max_abs_scaled_gradient'] >= .002 or item['convergence_messages']):
            raise RuntimeError('GLMM convergence checks failed')
    manifest.update(R_version=result['R_version'], packages=result['packages'])
    (out / 'provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
    effect = result['ensemble_minus_single_sensitivity']
    print(f"100 participants, 11400 trials; GLMM sensitivity difference {effect['estimate']:.5f}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--refit', action='store_true')
    modes.add_argument('--glmm', action='store_true')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--cores', type=int, default=4)
    parser.add_argument('--rscript', default=shutil.which('Rscript') or 'Rscript')
    args = parser.parse_args()
    if args.seed < 0 or args.cores < 1:
        parser.error('seed must be nonnegative and cores positive')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    default = f"{'glmm' if args.glmm else 'refit'}-{stamp}" if args.refit or args.glmm else 'reproduced'
    out = (args.out or RESULTS / default).resolve()
    if out == RESULTS.resolve():
        parser.error('--out must not be the directory containing the saved paper results')
    out.mkdir(parents=True, exist_ok=not (args.refit or args.glmm))
    data = json.loads(DATA.read_text())
    if [p['PROLIFIC_PID'] for p in data] != [f'P{i:03d}' for i in range(1, 101)]:
        raise ValueError('Expected canonical P001–P100 order')
    if args.glmm:
        run_glmm(data, out, args.seed, args.rscript)
        print(f'Outputs: {out}')
        return
    import arviz as az
    from summarize import diagnostics, summarize
    from plot import plot_average_psychometric_curves
    provenance = json.loads((RESULTS / 'provenance.json').read_text())
    if sha(DATA) != provenance['data_sha256']:
        raise ValueError('Data differ from the paper fit')
    settings = dict(seed=args.seed, draws=15000, tune=4000, chains=4,
                    cores=min(args.cores, 4), target_accept=.99, efficient=True, init='adapt_diag')
    if args.refit:
        from model import load_and_process_data, infer_hierarchical_psychometric_function
        processed = load_and_process_data(DATA)
        trace = infer_hierarchical_psychometric_function(processed, seed=args.seed,
                    draws=15000, tune=4000, cores=args.cores, target_accept=.99, efficient=True)
        trace.posterior.attrs.update(random_seed=args.seed,
            participant_ids=json.dumps([p['PROLIFIC_PID'] for p in data]), data_sha256=sha(DATA))
        trace_path = out / 'posterior.nc'
        trace.to_netcdf(trace_path)
    else:
        trace_path = RESULTS / 'posterior.nc'
        if sha(trace_path) != provenance['posterior_sha256']:
            raise ValueError('Saved posterior differs from the paper fit')
        trace = az.from_netcdf(trace_path)
        settings = {k: provenance[k] for k in settings}
    if trace.posterior.attrs['data_sha256'] != sha(DATA):
        raise ValueError('Posterior/data hash mismatch')
    checks = diagnostics(trace)
    if not checks['passed']:
        raise RuntimeError('Sampling diagnostics failed')
    summary = summarize(trace, data, out)
    plot_average_psychometric_curves(out / 'participant_estimates.csv', args.seed, out / 'curves.pdf')
    manifest = dict(environment(), fit=settings, figure_seed=args.seed, diagnostics=checks,
                    data_sha256=sha(DATA), posterior_sha256=sha(trace_path),
                    code_sha256={p.name: sha(p) for p in sorted(HERE.glob('*.py'))},
                    files_sha256={p.name: sha(p) for p in out.iterdir()
                                  if p.is_file() and p.name != 'provenance.json'})
    (out / 'provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
    ratio = summary.set_index('quantity').loc['population_median_width_ratio']
    print(f"100 participants, 11400 trials; diagnostics passed.")
    print(f"Population width ratio: {ratio['mean']:.5f} [95% CrI {ratio['hdi_low']:.5f}, {ratio['hdi_high']:.5f}].")
    print(f'Outputs: {out}')


if __name__ == '__main__':
    main()
