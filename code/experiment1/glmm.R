# Experiment 1 binomial GLMMs.
suppressPackageStartupMessages(library(lme4))
suppressPackageStartupMessages(library(jsonlite))
args <- commandArgs(trailingOnly=TRUE)
out <- args[[1]]
seed <- if (length(args) >= 2) as.integer(args[[2]]) else 42L
set.seed(seed)
dat <- read.csv(file.path(out, 'data.csv'))
dat$LMass <- log(dat$Mass)
dat$Subject <- factor(dat$Subject)
# Use multi as the reference level.
dat$Type <- factor(dat$Type, levels=c('multi', 'single'))
stopifnot(nrow(dat)==11400, nlevels(dat$Subject)==100,
          all(table(dat$Subject,dat$Type)==57), all(dat$Response %in% c(0,1)))
options(contrasts=c('contr.treatment','contr.poly'))
# Calculate derivatives for convergence checks.
control <- glmerControl(optimizer='bobyqa',optCtrl=list(maxfun=2e5),calc.derivs=TRUE)
formulas <- list(
  full=Response ~ Type*LMass + (Type*LMass | Subject),
  base=Response ~ LMass + (LMass | Subject),
  fixedint=Response ~ 0 + Type:LMass + (0 + Type:LMass | Subject),
  no_interaction=Response ~ Type + LMass + (Type*LMass | Subject)
)
models <- list()
diagnostics <- list()
for (name in names(formulas)) {
  cat('\nFitting',name,'\n'); flush.console()
  warnings <- character()
  start <- proc.time()[['elapsed']]
  fit <- withCallingHandlers(glmer(formulas[[name]], data=dat, family=binomial,
                                  control=control, nAGQ=1),
                             warning=function(w) {warnings <<- c(warnings,conditionMessage(w))})
  initial <- list(log_likelihood=as.numeric(logLik(fit)),singular=isSingular(fit),
                  coefficients=as.list(fixef(fit)),convergence=fit@optinfo$conv)
  optimizer_checks <- NULL
  if (name %in% c('full','no_interaction')) {
    # Compare optimizers and retain the highest likelihood.
    fit@call$formula <- formula(fit)
    fit@call$control <- quote(glmerControl(optimizer='bobyqa',optCtrl=list(maxfun=2e5),calc.derivs=TRUE))
    alternatives <- allFit(fit,data=dat,maxfun=2e5,parallel=if(.Platform$OS.type=='windows') 'no' else 'multicore',ncpus=4,
                           start_from_mle=FALSE)
    optimizer_checks <- lapply(alternatives,function(f) {
      if(!inherits(f,'merMod')) return(list(error=as.character(f)))
      list(log_likelihood=as.numeric(logLik(f)),singular=isSingular(f),
           coefficients=as.list(fixef(f)),convergence=f@optinfo$conv)
    })
    best <- alternatives[[which.max(sapply(alternatives,function(f)
      if(inherits(f,'merMod')) as.numeric(logLik(f)) else -Inf))]]
    # Skip the preliminary nAGQ=0 stage when restarting, so its inferior boundary
    # solution cannot replace the better nAGQ=1 starting point.
    refined <- glmer(formulas[[name]],data=dat,family=binomial,nAGQ=1,
      start=list(theta=getME(best,'theta'),fixef=fixef(best)),
      control=glmerControl(optimizer='bobyqa',nAGQ0initStep=FALSE,calc.derivs=TRUE,
                           optCtrl=list(maxfun=2e5,rhoend=1e-9)))
    # Keep the better likelihood if a restart fails to improve it.
    fit <- if(as.numeric(logLik(refined)) >= as.numeric(logLik(best))) refined else best
  }
  models[[name]] <- fit
  saveRDS(fit,file.path(out,paste0(name,'.rds')))
  print(summary(fit))
  hessian <- fit@optinfo$derivs$Hessian
  gradient <- fit@optinfo$derivs$gradient
  scaled <- tryCatch(solve(chol(hessian),gradient),error=function(e) NA_real_)
  diagnostics[[name]] <- list(formula=paste(deparse(formulas[[name]]),collapse=' '),
    seconds=proc.time()[['elapsed']]-start, warnings=warnings,
    initial_bobyqa=initial, optimizer_checks=optimizer_checks,
    optimizer_code=fit@optinfo$conv$opt, convergence_messages=fit@optinfo$conv$lme4$messages,
    singular=isSingular(fit), max_abs_scaled_gradient=max(abs(scaled)),
    hessian_min_eigenvalue=if(is.null(hessian)) NA_real_ else min(eigen(hessian,symmetric=TRUE,only.values=TRUE)$values),
    log_likelihood=as.numeric(logLik(fit)), AIC=AIC(fit), BIC=BIC(fit),
    random_effects=as.data.frame(VarCorr(fit)))
  co <- as.data.frame(coef(summary(fit)))
  co$term <- rownames(co)
  write.csv(co,file.path(out,paste0(name,'-coefficients.csv')),row.names=FALSE)
}
# Compare the fitted models.
original_base <- anova(models$base,models$full,test='Chisq')
original_fixed <- anova(models$fixedint,models$full,test='Chisq')
write.csv(as.data.frame(original_base),file.path(out,'original-base-v-full.csv'))
write.csv(as.data.frame(original_fixed),file.path(out,'original-fixedint-v-full.csv'))
# Test the condition-by-mass interaction with matching random effects.
interaction_test <- anova(models$no_interaction,models$full,test='Chisq')
write.csv(as.data.frame(interaction_test),file.path(out,'interaction-lrt.csv'))
b <- fixef(models$full)
v <- as.matrix(vcov(models$full))
contrast <- -b[['Typesingle:LMass']]
se <- sqrt(v['Typesingle:LMass','Typesingle:LMass'])
z <- contrast/se
participant <- coef(models$full)$Subject
participant$Subject <- rownames(participant)
participant$ensemble_sensitivity <- participant$LMass
participant$single_sensitivity <- participant$LMass+participant[['Typesingle:LMass']]
write.csv(participant,file.path(out,'participant-coefficients.csv'),row.names=FALSE)
pred <- predict(models$full,type='response')
write.csv(aggregate(cbind(observed=dat$Response,predicted=pred),
                    by=list(Type=dat$Type,Mass=dat$Mass),FUN=mean),
          file.path(out,'conditional-predictions.csv'),row.names=FALSE)
report <- list(seed=seed, method='Maximum likelihood GLMM, binomial-logit, Laplace approximation (nAGQ=1)',
  R_version=R.version.string, platform=R.version$platform,
  packages=list(lme4=as.character(packageVersion('lme4')),Matrix=as.character(packageVersion('Matrix')),
                jsonlite=as.character(packageVersion('jsonlite'))),
  fitting_settings=list(nAGQ=1,initial_optimizer='bobyqa',maxfun=200000,
    full_and_null_checks='allFit, cold starts, 4 workers; maximum likelihood candidate, then tight bobyqa restart',
    restart_rhoend=1e-9,thread_limits=Sys.getenv(c('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS'))),
  diagnostics=diagnostics,
  ensemble_sensitivity=b[['LMass']], single_sensitivity=b[['LMass']]+b[['Typesingle:LMass']],
  ensemble_minus_single_sensitivity=list(estimate=contrast,se=se,z=z,
    p_two_sided=2*pnorm(-abs(z)),wald_95_CI=c(contrast-qnorm(.975)*se,contrast+qnorm(.975)*se)),
  interaction_lrt=as.data.frame(interaction_test),
  original_base_v_full=as.data.frame(original_base),original_fixedint_v_full=as.data.frame(original_fixed),
  participant_positive_contrasts=sum(participant$ensemble_sensitivity>participant$single_sensitivity))
write_json(report,file.path(out,'results.json'),pretty=TRUE,auto_unbox=TRUE,digits=16,null='null')
capture.output(sessionInfo(),file=file.path(out,'sessionInfo.txt'))
print(report$ensemble_minus_single_sensitivity)
print(interaction_test)
