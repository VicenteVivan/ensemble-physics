"""Simulation and analytic checks of model probabilities."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import model
Lookup, analytic_md, LAPSE, s2_probabilities = model.Lookup, model.analytic_md, model.LAPSE, model.s2_probabilities
SEEDS = model.SEEDS


def response_gated_joint(e, attended, changed, k, r, direction=1):
    """Validate the lookup using simulated evidence and both possible MD responses."""
    total = (e*attended).sum(1)*direction
    md = np.where(total > 1, 1., np.where(total < -1, 0., .5))
    cl = []
    for sign in (direction, -direction):
        detected = (sign*e > 1)&attended
        count = detected.sum(1)
        success = np.divide((detected&changed).sum(1), count,
                            out=np.zeros(len(k)), where=count > 0)
        cl.append(np.where(count > 0, success, (5-r)/(25-k)))
    return np.stack([md*cl[0], (1-md)*cl[1], md*(1-cl[0]), (1-md)*(1-cl[1])], axis=1)


def simulate(lam, mu, sigma, n=300000, seed=SEEDS["validation_base"], direction=1, cap=8):
    rng=np.random.default_rng(seed)
    k=np.minimum(rng.poisson(lam,n),cap)
    r=rng.hypergeometric(5,20,k)
    pos=np.arange(cap)[None,:]
    attended=pos<k[:,None];changed=pos<r[:,None]
    e=rng.normal(0,sigma,(n,cap))+direction*mu*changed
    values = response_gated_joint(e, attended, changed, k, r, direction)
    return values.mean(0), values.std(0)/np.sqrt(n)


def validate(prefix):
    lookup=Lookup(prefix)
    cases=[(2.94,2.83,.8),(4,1,1),(2,.6,.3),(6,5,1.5),(4,8,.3),
           (8,2,2),(1,.8,.15),(12,3,.8),(3,.05,1),(3,1.5,3)]
    rows=[]
    for index,(lam,mu,sigma) in enumerate(cases):
        predicted=lookup.predict([lam],[mu],[sigma],[0])[0]
        observed,se=simulate(lam,mu,sigma,seed=SEEDS["validation_base"]+index)
        analytic=analytic_md(lam,mu,sigma)
        row={'lambda':lam,'mu':mu,'sigma':sigma,'predicted':predicted.tolist(),
             'simulated':observed.tolist(),'simulation_se':se.tolist(),
             'max_joint_error':float(np.max(abs(predicted-observed))),
             'analytic_MD_error':float(abs(predicted[[0,2]].sum()-analytic))}
        rows.append(row)
    positive,_=simulate(3,2.83,.8,seed=SEEDS["direction_forward"])
    negative,_=simulate(3,2.83,.8,seed=SEEDS["direction_reverse"],direction=-1)
    zero=lookup.predict([0],[2.83],[.8],[0])[0]
    if not np.allclose(zero,LAPSE,atol=1e-7):
        raise AssertionError(('zero attention',zero))
    p2=s2_probabilities(np.array([.1,2.83,8]),np.array([.15,.8,3]))
    if not np.allclose(p2.sum(-1),1) or not np.allclose(p2[:,0,0],p2[:,2,2]):
        raise AssertionError('S2 normalization/symmetry')
    result={'mode':'response-gated','cases':rows,'direction_symmetry_max_error':float(max(abs(positive-negative))),
            'zero_attention':zero.tolist(),'lapse_only_S1':LAPSE.tolist(),
            'max_joint_error':max(r['max_joint_error'] for r in rows),
            'max_analytic_MD_error':max(r['analytic_MD_error'] for r in rows),
            'tolerance':.005}
    result['passed']=(result['max_joint_error']<.005 and result['max_analytic_MD_error']<.005
                      and result['direction_symmetry_max_error']<.005)
    import pytensor
    import pytensor.tensor as pt
    arrays = [np.array(x, dtype=float) for x in
              [[0, 1, 3, 8, 12], [2, 1.5, 2.83, 8, .5], [1, .3, .8, 2, 3], [0, -.3, .327, .6, -1]]]
    pred = lookup.predict(*arrays)
    variables = [pt.dvector(n) for n in ['lam', 'mu', 'sigma', 'delta']]
    fn = pytensor.function(variables, lookup.tensor_predict(*variables), mode='FAST_COMPILE')
    error = float(np.max(abs(fn(*arrays)-pred)))
    result.update(numpy_tensor_max_error=error, normalization_max_error=float(np.max(abs(pred.sum(1)-1))))
    result['passed'] = bool(result['passed'] and error < 1e-10 and np.all(pred >= 0) and np.allclose(pred.sum(1),1))
    result['lookup_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in Path(prefix).parent.glob(Path(prefix).name+'_*.npy')}
    result['seeds']=dict(SEEDS)
    result['simulation_trials_per_case']=300000
    return result



import arviz as az
from scipy.special import expit
from lookup import build_point

def audit(trace_path,prefix):
    post=az.from_netcdf(trace_path).posterior
    arrays=[post[n].values.reshape(-1) for n in ['λ','μ_gain','σ','delta']]
    lam,mu,sigma,delta=arrays
    lookup=Lookup(prefix)
    a,b=(1-mu)/sigma,-np.log(sigma)
    rng=np.random.default_rng(SEEDS["posterior_selection"])
    selected=np.unique(np.r_[rng.choice(len(lam),60,replace=False),
                            np.argmin(a),np.argmax(a),np.argmin(b),np.argmax(b),
                            np.argmax(lam),np.argmin(mu),np.argmax(mu),np.argmax(sigma)])
    rows=[]
    for ix in selected:
        args=[np.array([v[ix]]) for v in arrays]
        table = build_point(a[ix], b[ix], dz=.02)
        f = np.clip(table[:, :2], 1e-7, 1-1e-7)
        base=np.clip(.5+.5*(1-f[:,0]-f[:,1]),1e-12,1-1e-12)
        md=expit(np.log(base)-np.log1p(-base)+delta[ix])
        w=lookup.weights(*args[:3])[0];cl=lookup.cl
        cl_wrong = np.clip(table[:, 2]/(1-base), 0, 1)
        direct=np.array([sum(w*cl*md),sum(w*cl_wrong*(1-md)),sum(w*(1-cl)*md),sum(w*(1-cl_wrong)*(1-md))])
        predicted=lookup.predict(*args)[0]
        rows.append({'flat_index':int(ix),'lambda':float(lam[ix]),'mu':float(mu[ix]),
                     'sigma':float(sigma[ix]),'delta':float(delta[ix]),
                     'max_joint_error':float(max(abs(predicted-direct)))})
    # Independent continuous-evidence simulation checks the points with the
    # largest joint quadrature discrepancies (zero boost has an explicit rule).
    checks=[]
    for row in sorted(rows,key=lambda x:x['max_joint_error'],reverse=True)[:10]:
        ix=row['flat_index'];args=[np.array([v[ix]]) for v in arrays[:3]]
        predicted=lookup.predict(*args,np.array([0]))[0]
        sim,se=simulate(lam[ix],mu[ix],sigma[ix],seed=SEEDS["posterior_simulation_base"]+len(checks))
        checks.append({'flat_index':ix,'max_joint_error':float(max(abs(predicted-sim))),
                       'max_simulation_se':float(max(se)),
                       'analytic_MD_error':float(abs(predicted[[0,2]].sum()-analytic_md(lam[ix],mu[ix],sigma[ix])))})
    result={'mode':'response-gated','seeds':dict(SEEDS),'direct_dz':.02,'quadrature_points':rows,'simulation_points':checks,
            'max_direct_joint_error':max(r['max_joint_error'] for r in rows),
            'max_simulated_joint_error':max(r['max_joint_error'] for r in checks),
            'max_analytic_MD_error':max(r['analytic_MD_error'] for r in checks),'tolerance':.005}
    result['passed']=max(result[k] for k in ['max_direct_joint_error','max_simulated_joint_error','max_analytic_MD_error'])<.005
    return result

