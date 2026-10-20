"""Reproduce Experiment 2, or optionally refit with seed 42."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

for key in ['OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS']:
    os.environ.setdefault(key, '1')
os.environ.setdefault('PYTENSOR_FLAGS', 'cxx=,linker=py')
os.environ.setdefault('MPLBACKEND', 'Agg')

import model
from summarize import report
from plot import plot_figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refit', action='store_true')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--out', type=Path, help='Output directory; defaults to results/experiment2/reproduced')
    args = parser.parse_args()
    if args.seed < 0:
        parser.error('seed must be nonnegative')
    if args.refit:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        out = args.out or model.RESULTS/f'refit-{stamp}'
        trace = model.fit(out, seed=args.seed)
        fit_record = json.loads((out/'provenance.json').read_text())
        from numerics import audit
        numerical = audit(trace, model.LOOKUP)
        fit_record.update(posterior_numerics=numerical,
                          status='numerical_passed' if numerical['passed'] else 'failed')
        (out/'provenance.json').write_text(json.dumps(fit_record, indent=2)+'\n')
    else:
        out = args.out or model.RESULTS/'reproduced'
        trace = model.RESULTS/'trace.nc'
        fit_record = json.loads((model.RESULTS/'provenance.json').read_text())
        if model.sha256(trace) != fit_record['trace_sha256']:
            raise RuntimeError('Saved posterior changed')
        for name, digest in fit_record['inputs'].items():
            if name.startswith('data/') or name.endswith('.npy'):
                if model.sha256(model.ROOT/name) != digest:
                    raise RuntimeError(f'Saved data or lookup changed: {name}')
        numerical = fit_record['posterior_numerics']
    out = out.resolve()
    if not args.refit and out == model.RESULTS.resolve():
        parser.error('Choose a separate output directory to preserve the saved paper results')
    out.mkdir(parents=True, exist_ok=True)
    summary = report(trace, model.LOOKUP, out, numerical_result=numerical)
    inputs = [trace, *model.DATA.glob('*'), *model.HERE.glob('*.py'),
              model.HERE/'requirements.txt', model.HERE/'style.json',
              *model.HERE.glob('lookup/*.npy')]
    provenance = dict(model='response-conditioned localization, shared evidence SD', status='passed',
                      environment=model.environment(), fit_settings=fit_record['fit_settings'],
                      seeds=fit_record['seeds'], selected_ids=summary['raw_accuracy']['selected_ids'],
                      trace_sha256=model.sha256(trace), diagnostics=summary['sampling_diagnostics'],
                      posterior_numerics=numerical,
                      inputs={os.path.relpath(p, model.ROOT):model.sha256(p) for p in inputs})
    dest = out/'provenance.json'
    dest.write_text(json.dumps(provenance, indent=2)+'\n')
    provenance['figure'] = plot_figure(out, trace, out/'figure5.pdf')
    provenance['outputs'] = {p.name:model.sha256(p) for p in sorted(out.iterdir())
                             if p.is_file() and p.name != 'provenance.json'}
    dest.write_text(json.dumps(provenance, indent=2)+'\n')
    raw = summary['raw_accuracy']
    boost = summary['boost_observed_scale']
    print(f"Participants: {raw['selected']} of {raw['eligible']} eligible; "
          f"S1 trials: {sum(raw['s1_counts'])}; S2 trials: {sum(map(sum,raw['s2_counts']))}")
    print(f"Ensemble boost: {100*boost['mean']:.2f} percentage points "
          f"(95% CrI [{100*boost['hdi95'][0]:.2f}, {100*boost['hdi95'][1]:.2f}])")
    print(f"Sampling diagnostics passed; outputs: {out}")


if __name__ == '__main__':
    main()
