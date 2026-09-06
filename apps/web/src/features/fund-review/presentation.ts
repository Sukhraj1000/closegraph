import type {Finding, FundWork} from './api';
import type {SourceFile, Issue} from '../collections/model';

export function findingTitle(finding: Finding) {
 const key = ['reference','unique'].includes(finding.kind) && Array.isArray(finding.observed)
  ? finding.observed.map(value=>value==null||value===''?'Blank value':String(value)).join(' / ')
  : '';
 const affected = typeof finding.affected_count==='number' && finding.affected_count>0
  ? `${finding.affected_count.toLocaleString()} affected ${finding.affected_count===1?'record':'records'}` : '';
 return [finding.title,key,affected].filter(Boolean).join(' · ');
}

export function fileFailure(source:SourceFile, issues:Issue[] = []) {
 const failures=[...(source.issues??[]),...issues.filter(issue=>issue.source_id===source.id)].filter(issue=>!issue.resolved);
 if(failures.some(issue=>issue.code==='storage_full'||/no space left|ENOSPC|disk quota|storage is full/i.test(issue.message)))
  return "Storage is full. Free disk space on the app’s computer, then retry processing. Your original file is retained.";
 if(failures.some(issue=>/provider|reducto|unavailable|connection|timed? ?out/i.test(issue.message)))
  return 'The document reader was unavailable. Check the connection or parser setup, then retry processing. Your original file is retained.';
 return 'This file could not be read. Retry processing; if it fails again, inspect the original file and the extraction details below.';
}

export const readableDate=(value:unknown)=>typeof value==='string'&&!Number.isNaN(Date.parse(value))
 ?new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):'';

export function actorLabel(actor:unknown, work:FundWork) {
 if(actor==='system'||actor==='System')return 'System';
 return work.members?.find(member=>member.actor_id===actor)?.display_name
  ?? ({accountant:'Accountant',preparer:'Accountant',account_manager:'Account manager',reviewer:'Account manager',fund_manager:'Fund manager',investor:'Investor'}[String(actor)])
  ?? (actor===work.access?.actor_id?'You':'Team member');
}
