"""Paper summaries from probabilities evaluated separately for every posterior draw."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

import arviz as az
import numpy as np
from scipy.special import ndtr
from scipy.stats import poisson

import model
selected_data, sha256, ROOT = model.selected_data, model.sha256, model.ROOT
Lookup, analytic_md, LAPSE, s2_probabilities = model.Lookup, model.analytic_md, model.LAPSE, model.s2_probabilities
diagnostics = model.diagnostics


def summarize(x):
    x=np.asarray(x).ravel()
    hdi=az.hdi(x,hdi_prob=.95)
    return {'mean':float(x.mean()),'hdi95':[float(v) for v in hdi]}


def distribution(x):
    x=np.asarray(x)
    return {'mean':float(x.mean()),'p50':float(np.quantile(x,.5)),
            'p95':float(np.quantile(x,.95)),'p99':float(np.quantile(x,.99)), 'max':float(x.max())}


def posterior_joint(lookup,lam,mu,sigma,delta,batch_size=1024):
    """Predict each draw/subject combination; never predict at averaged parameters."""
    shape=lam.shape
    if len(shape)!=2 or any(v.shape!=shape for v in [mu,sigma,delta]):
        raise ValueError('Expected aligned (sample,subject) arrays')
    p1=np.empty((lam.size,4));p0=np.empty_like(p1)
    flat=[a.ravel() for a in [lam,mu,sigma,delta]]
    for start in range(0,len(p1),batch_size):
        end=start+batch_size
        p1[start:end],p0[start:end]=lookup.predict(*[a[start:end] for a in flat],return_zero=True)
    return p1.reshape(*shape,4),p0.reshape(*shape,4)


def posterior_predictive(p1,p2,s1,s2,seed=model.SEEDS["posterior_predictive"]):
    rng=np.random.default_rng(seed)
    indices=np.linspace(0,len(p1)-1,min(1000,len(p1)),dtype=int)
    p1,p2=p1[indices],p2[indices]
    n1,n2=s1.sum(1),s2.sum(2)
    expected1=p1*n1[None,:,None]
    expected2=p2*n2[None,:,:,None]
    replica1=rng.multinomial(n1[None,:],p1)
    replica2=rng.multinomial(n2[None,:,:],p2)
    result={}
    for name,expected,replicated,observed in [('S1',expected1,replica1,s1),('S2',expected2,replica2,s2)]:
        axes=tuple(range(1,expected.ndim))
        obs_discrepancy=(((observed[None]-expected)**2)/(expected+.5)).sum(axis=axes)
        rep_discrepancy=(((replicated-expected)**2)/(expected+.5)).sum(axis=axes)
        result[name]={'observed_counts':observed.sum(0).tolist(),
                      'expected_count_mean':expected.sum(1).mean(0).tolist(),
                      'expected_count_interval95':np.quantile(expected.sum(1),[.025,.975],axis=0).tolist(),
                      'replicated_count_interval95':np.quantile(replicated.sum(1),[.025,.975],axis=0).tolist(),
                      'posterior_predictive_pvalue':float(np.mean(rep_discrepancy>=obs_discrepancy))}
    result.update(draws=len(indices),seed=seed,
                  discrepancy='sum (count - expected)^2 / (expected + 0.5); in-sample diagnostic')
    return result


def report(trace_path,prefix,out,label="Response-conditioned localization",numerical_result=None):
    mode = "response-gated"
    started=time.monotonic();out.mkdir(parents=True,exist_ok=True)
    if numerical_result is None:
        from numerics import audit
        numerical_result=audit(trace_path,prefix)
    if not numerical_result['passed']:
        raise RuntimeError('Posterior numerical checks failed; report withheld')
    trace=az.from_netcdf(trace_path);post=trace.posterior
    _,_,selected,s1,s2=selected_data();ids=[s['PROLIFIC_PID'] for s in selected]
    s1,s2=np.array(s1),np.array(s2)
    if post.attrs.get('model_variant') != 'response-gated-free':
        raise ValueError('Expected the response-conditioned shared-noise model')
    if json.loads(post.attrs.get('selected_ids', '[]'))!=ids or list(post.subject.values)!=ids:
        raise ValueError('Trace/data participant identity mismatch')
    S=len(ids);C=post.sizes['chain'];D=post.sizes['draw'];samples=C*D
    def values(name):
        a=post[name]
        dims=[d for d in a.dims if d not in ('chain','draw')]
        if len(dims)!=1 or a.sizes[dims[0]]!=S:
            raise ValueError(f'Participant shape mismatch for {name}')
        return a.transpose('chain','draw',dims[0]).values.reshape(samples,S)
    lam,mu,sigma,delta,alpha=(values(n) for n in ['λ','μ_gain','σ','delta','alpha'])
    diag,_=diagnostics(trace)
    if not diag["passed"]:
        raise RuntimeError("Sampling diagnostics failed")
    lookup=Lookup(prefix)
    # Predict at every draw; p0 sets delta to zero with the other parameters fixed.
    p1,p0=posterior_joint(lookup,lam,mu,sigma,delta)
    p2=s2_probabilities(mu,sigma)
    # Mix evidence-based predictions with guessing to obtain observed-scale rates.
    obs1=(1-alpha[:,:,None])*p1+alpha[:,:,None]*LAPSE
    obs0=(1-alpha[:,:,None])*p0+alpha[:,:,None]*LAPSE
    obs2=(1-alpha[:,:,None,None])*p2+alpha[:,:,None,None]/3
    n2=s2.sum(2);changed_n=n2[:,0]+n2[:,2]
    human={'MD':(s1[:,0]+s1[:,2])/s1.sum(1),'CL':(s1[:,0]+s1[:,1])/s1.sum(1),
           'changed':(s2[:,0,0]+s2[:,2,2])/changed_n,'same':s2[:,1,1]/n2[:,1]}
    def rates(a,b):
        return {'MD':a[:,:,0]+a[:,:,2], 'CL':a[:,:,0]+a[:,:,1],
                'changed':(b[:,:,0,0]*n2[None,:,0]+b[:,:,2,2]*n2[None,:,2])/changed_n,
                'same':b[:,:,1,1]}
    latent_rates,observed_rates=rates(p1,p2),rates(obs1,obs2)
    # Average draws for participant predictions, participants for group summaries.
    predicted={k:v.mean(0) for k,v in observed_rates.items()}
    summaries={'label':label,'mode':mode,'participants':S,'posterior_draws':samples,
               'participant_averaged_parameters':{k:summarize(v.mean(1)) for k,v in
                  [('attention_rate',lam),('evidence_mean',mu),('evidence_sd',sigma),('lapse',alpha),('delta',delta)]},
               'accuracy_latent':{k:summarize(v.mean(1)) for k,v in latent_rates.items()},
               'accuracy_observed_scale':{k:summarize(v.mean(1)) for k,v in observed_rates.items()},
               'boost_latent':summarize(((p1-p0)[:,:,0]+(p1-p0)[:,:,2]).mean(1)),
               'boost_observed_scale':summarize(((obs1-obs0)[:,:,0]+(obs1-obs0)[:,:,2]).mean(1))}
    summaries['MD_probability_ratio_observed_scale']=summarize(
        (obs1[:,:,0]+obs1[:,:,2]).mean(1)/(obs0[:,:,0]+obs0[:,:,2]).mean(1))
    expected_k=sum(poisson.sf(k,lam) for k in range(8))
    summaries['participant_average_capped_attention']=summarize(expected_k.mean(1))
    # Transform population locations separately from averages over participants.
    typical_mu=np.logaddexp(0,post['logμ_mu'].values.ravel())
    typical_sigma=np.exp(post['logσ_mu'].values.ravel())
    summaries['population_location_transforms']={
        'attention_rate':summarize(np.exp(post['logλ_mu'].values)),
        'evidence_mean':summarize(typical_mu),'evidence_sd':summarize(typical_sigma),
        'lapse_hypermean':summarize(post['alpha_mu'].values),
        'hit_one_direction_without_lapse':summarize(ndtr((typical_mu-1)/typical_sigma)),
        'false_alarm_one_direction_without_lapse':summarize(ndtr(-1/typical_sigma)),
        'false_alarm_either_direction_without_lapse':summarize(2*ndtr(-1/typical_sigma)),
        'same_without_lapse':summarize(1-2*ndtr(-1/typical_sigma))}
    if 'delta_mu' in post:
        summaries['delta_population_mean']=summarize(post['delta_mu'].values)
        summaries['conditional_odds_multiplier']=summarize(np.exp(post['delta_mu'].values))
        summaries['probability_delta_population_positive']=float((post['delta_mu'].values>0).mean())
    intervals=np.array([az.hdi(delta[:,j],hdi_prob=.95) for j in range(S)])
    summaries['individual_delta']={'positive_means':int((delta.mean(0)>0).sum()),
                                   'hdi95_above_zero':int((intervals[:,0]>0).sum()),
                                   'hdi95_below_zero':int((intervals[:,1]<0).sum())}
    diag,diagframe=diagnostics(trace)
    summaries['sampling_diagnostics']=diag
    aa,bb=(1-mu)/sigma,-np.log(sigma)
    clipped=(aa<lookup.a[0])|(aa>lookup.a[-1])|(bb<lookup.b[0])|(bb>lookup.b[-1])
    # Analytic MD permits exact audit of clipping/interpolation and attention cap.
    exact8=analytic_md(lam,mu,sigma,8)
    exact25=analytic_md(lam,mu,sigma,25)
    numerical={'lookup_outside_fraction':float(clipped.mean()),
               'participants_with_any_outside_draw':int(clipped.any(0).sum()),
               'lookup_zero_boost_MD_absolute_error':distribution(abs(p0[:,:,0]+p0[:,:,2]-exact8)),
               'probability_poisson_at_least_8':distribution(poisson.sf(7,lam)),
               'probability_poisson_above_8':distribution(poisson.sf(8,lam)),
               'MD_change_cap25_minus_cap8':distribution(exact25-exact8)}
    numerical['marginal_MD_error_passed']=numerical['lookup_zero_boost_MD_absolute_error']['max']<.005
    if clipped.any() or not numerical['marginal_MD_error_passed']:
        raise RuntimeError('Posterior lookup coverage or numerical accuracy failed')
    summaries['numerical_audit']=numerical
    summaries['posterior_predictive']=posterior_predictive(obs1,obs2,s1,s2)
    expected_s1 = (obs1*s1.sum(1)[None, :, None]).sum(1)
    summaries['conditional_localization_accuracy'] = {
        'given_MD_correct': summarize(expected_s1[:, 0]/(expected_s1[:, 0]+expected_s1[:, 2])),
        'given_MD_wrong': summarize(expected_s1[:, 1]/(expected_s1[:, 1]+expected_s1[:, 3])),
        'observed_given_MD_correct': float(s1[:, 0].sum()/s1[:, [0, 2]].sum()),
        'observed_given_MD_wrong': float(s1[:, 1].sum()/s1[:, [1, 3]].sum()),
        'estimand': 'Pooled expected-count ratios evaluated per posterior draw, then summarized'}
    summaries['in_sample_correlations']={k:float(np.corrcoef(predicted[k],human[k])[0,1]) for k in human}
    summaries['raw_accuracy']=model.raw_summary()[0]
    import csv
    with (out/'participant_estimates.csv').open('w') as f:
        keys=['subject']+[f'{kind}_{k}' for k in human for kind in ['observed','model']]+['delta_mean','delta_hdi_low','delta_hdi_high']
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
        for j,sid in enumerate(ids):
            row={'subject':sid,'delta_mean':delta[:,j].mean(),'delta_hdi_low':intervals[j,0],'delta_hdi_high':intervals[j,1]}
            for k in human:
                row[f'observed_{k}']=human[k][j];row[f'model_{k}']=predicted[k][j]
            writer.writerow(row)
    (out/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    with (out/'summary.csv').open('w', newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['quantity','mean','hdi95_low','hdi95_high'])
        def write_values(prefix, value):
            if isinstance(value,dict):
                if 'mean' in value and 'hdi95' in value:
                    writer.writerow([prefix,value['mean'],*value['hdi95']])
                else:
                    for key,item in value.items():
                        write_values(f'{prefix}.{key}' if prefix else key,item)
        write_values('',summaries)
        for task,value in summaries['raw_accuracy']['accuracy'].items():
            writer.writerow([f'raw_accuracy.{task}.participant_mean',value['participant_mean'],'',''])
        for task,r in summaries['in_sample_correlations'].items():
            writer.writerow([f'in_sample_correlation.{task}',r,'',''])
    trace.close()
    return summaries
