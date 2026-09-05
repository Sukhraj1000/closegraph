import { useState } from 'react';
import { formatDecimal, formatFactValue, locatorText, safeDownloadURL, type Fact, type PackSnapshot, type Source } from '../../lib/model';
export function DocumentPreview({title,context,source,facts=[],candidate,unavailable,stale=false}:{title:string;context?:string;source?:Source;facts?:Fact[];candidate?:PackSnapshot['candidate'];unavailable?:string;stale?:boolean}) {
 return <div className="paper"><p className="caption">{context ?? 'Source evidence'}</p><h3>{title}</h3>{unavailable ? <p>{unavailable}</p> : <>{Array.isArray(source?.preview_rows) && source.preview_rows.map((row,i)=><div className="paper-row" key={'source-'+i}><span>{String((row as {label?:string}).label??'Source value')}</span><strong>{String((row as {value?:string}).value??'—')}</strong></div>)}{facts.map(fact=><div className="paper-row" key={fact.fact_id}><span>{fact.metric}</span><strong>{formatFactValue(fact)}</strong></div>)}{candidate && <div className="paper-total"><span>{candidate.total_label??'Checked output total'}</span><strong>{formatDecimal(candidate.total_decimal,facts[0]?.currency)}</strong></div>}{source && <dl className="metadata"><div><dt>Source location</dt><dd>{locatorText(source.locator)}</dd></div>{Object.entries(source).filter(([key,value])=>['entity_id','currency','period','source_version','document_version_id','raw_value','raw_scale','status','context'].includes(key) && value!=null).map(([key,value])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{String(value)}</dd></div>)}</dl>}{source?.content_hash != null && <p className="hash">SHA-256 {String(source.content_hash)}</p>}</>}{stale && <p className="caption">Historical evidence. Recheck the current source version before approval.</p>}{candidate && <p className="caption">{candidate.released?'Reviewed workbook':'Candidate workbook · awaiting publication'}</p>}</div>;
}
export function DownloadLink({url,label,onInspect}:{url:string|null|undefined;label:string;onInspect?:()=>void}) {
 const safe=safeDownloadURL(url),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function download(event:React.MouseEvent<HTMLAnchorElement>){
  event.preventDefault();if(!safe||busy)return;setBusy(true);setError('');
  try{
   const response=await fetch(safe,{credentials:'same-origin',redirect:'error'});
   if(!response.ok)throw new Error('Download unavailable (HTTP '+response.status+'). Refresh the current version and check your source access.');
   const bytes=await response.blob(),disposition=response.headers.get('content-disposition')??'';
   let filename='closegraph-download';const encoded=disposition.match(/filename\*=UTF-8''([^;]+)/i),plain=disposition.match(/filename="?([^";]+)"?/i);
   try{filename=encoded?decodeURIComponent(encoded[1]):plain?.[1]??filename;}catch{}
   filename=filename.replace(/[\\/]/g,'_');
   const objectURL=URL.createObjectURL(bytes),anchor=document.createElement('a');anchor.href=objectURL;anchor.download=filename;document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(objectURL),30000);onInspect?.();
  }catch(error){setError((error as Error).message);}finally{setBusy(false);}
 }
 return safe?<span><a className="button button-outline" href={safe} download onClick={event=>void download(event)} aria-disabled={busy}>{busy?'Preparing download…':label}</a>{error&&<span role="alert" className="field-error">{error}</span>}</span>:<span className="caption">Download unavailable until the server provides a verified artifact.</span>;
}
