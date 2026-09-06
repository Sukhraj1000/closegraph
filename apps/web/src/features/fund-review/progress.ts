/** Older saved jobs have only kind/status; document counts are optional. */
export function progressLabel(value:unknown):string {
 const p=value&&typeof value==='object'?value as Record<string,unknown>:{};
 const fallback=p.kind==='fund_review'?'Preparing review findings':'Reading documents and preparing review findings';
 const stage=typeof p.stage==='string'&&p.stage.trim()&&!['undefined','null'].includes(p.stage)?p.stage:fallback;
 const done=p.completed_documents,total=p.total_documents;
 const valid=typeof done==='number'&&Number.isInteger(done)&&done>=0&&typeof total==='number'&&Number.isInteger(total)&&total>0&&done<=total;
 return valid?`${stage} · ${done} of ${total} documents`:stage;
}
