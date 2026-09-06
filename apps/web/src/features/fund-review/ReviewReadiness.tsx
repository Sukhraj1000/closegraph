import {useEffect,useState} from 'react';
import type {BriefResults,Finding,FundReviewApi,FundWork,ReviewConfig,TableProfile} from './api';
import {selectionDescription} from './Checks';

export function actionableCount(summary:Record<string,unknown>,status:'difference'|'needs_input'|'passed'):unknown {
 return status==='difference'?summary.blocking_difference??summary.difference??summary.differences:status==='needs_input'?summary.blocking_needs_input??summary.needs_input:summary.passed??summary.passed_checks;
}
export function reviewBlockers(work:FundWork,results:BriefResults|null):string[] {
 const run=work.fund_review,blockers:string[]=[];
 if(!results||results.stale||run?.stale||run?.status!=='COMPLETE'||(results.version!==undefined&&results.version!==work.version)||['QUEUED','PROCESSING'].includes(work.status))return ['Wait for current checks to finish, or rerun if the evidence has changed.'];
 const checks=run.config.checks;
 if(!checks.length||checks.some(c=>!c.confirmed))blockers.push('Choose and confirm the checks this review should cover.');
 if(typeof results.summary.passed!=='number'||results.summary.passed<1)blockers.push('A passing result is needed for the selected checks.');
 for(const status of ['difference','needs_input'] as const){const count=actionableCount(results.summary,status);if(typeof count==='number'&&count>0)blockers.push(status==='difference'?`${count.toLocaleString()} ${count===1?'difference still needs':'differences still need'} to be resolved.`:`${count.toLocaleString()} ${count===1?'finding still needs':'findings still need'} your input.`);else if(typeof count!=='number')blockers.push('Load the complete check summary before deciding.');}
 if(results.coverage.complete!==true)blockers.push('Complete the source coverage and interpretation review.');
 if(work.tasks?.some(t=>t.active!==false&&t.blocking&&t.status!=='resolved'))blockers.push('Resolve the outstanding blocking requests.');
 if(work.requirements?.some(r=>r.blocking!==false&&!work.check_results?.some(c=>c.requirement_id===r.id&&(c.outcome??c.status)==='PASS')))blockers.push('Required evidence or financial checks remain incomplete.');
 return [...new Set(blockers)];
}
export function ReviewScope({config,tables}:{config:ReviewConfig;tables:TableProfile[]}) {
 return <details className="fr-review-scope"><summary>Exact scope of this review · {config.checks.length} selected {config.checks.length===1?'check':'checks'}</summary>{config.checks.length?<ul>{config.checks.map(check=><li key={check.id}><strong>{check.title}</strong><p>{selectionDescription(check.left,tables)}{check.right?' → '+selectionDescription(check.right,tables):''}</p>{check.kind==='totals'&&<p>Allowed difference: {check.tolerance??'0'}. Only the selected grouped totals are compared.</p>}</li>)}</ul>:<p>No checks are confirmed yet.</p>}<p>This release covers these selections and saved source versions only. It does not verify unselected formulas, valuations, accounting policy or the entire reporting pack.</p></details>;
}
export function SupportingNotes({api,workId,version,total,onSelect}:{api:FundReviewApi;workId:string;version:number;total:number;onSelect:(finding:Finding)=>void}) {
 const [open,setOpen]=useState(false),[offset,setOffset]=useState(0),[page,setPage]=useState<BriefResults|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState('');
 useEffect(()=>{setOffset(0);setPage(null);},[workId,version]);
 useEffect(()=>{if(!open)return;let active=true;setLoading(true);setPage(null);setError('');api.results(workId,'','',offset,false).then(value=>{if(active)setPage(value);}).catch(e=>{if(active)setError(e instanceof Error?e.message:'Supporting notes could not be loaded.');}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[api,workId,version,open,offset]);
 return <section className="fr-supporting-notes"><button className="fr-text-button" aria-expanded={open} onClick={()=>setOpen(!open)}>{total.toLocaleString()} supporting {total===1?'note':'notes'} outside the selected checks</button><p>These notes do not block this review scope. Their contents have not passed verification.</p>{open&&<>{loading&&<p role="status">Loading supporting notes…</p>}{error&&<p role="alert">{error}</p>}{page?.findings.map(finding=><button className="fr-supporting-note" key={finding.id} onClick={()=>onSelect(finding)}><span className="fr-label">Supporting note · not verified</span><strong>{finding.title}</strong><p>{finding.explanation}</p><span>View note and evidence →</span></button>)}{page&&page.total>50&&<div className="fr-pagination"><span>{offset+1}–{Math.min(offset+50,page.total)} of {page.total} notes</span><button className="fr-button secondary" disabled={loading||offset===0} onClick={()=>setOffset(Math.max(0,offset-50))}>Previous notes</button><button className="fr-button secondary" disabled={loading||offset+50>=page.total} onClick={()=>setOffset(offset+50)}>Next notes</button></div>}</>}</section>;
}
