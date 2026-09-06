import {useState} from 'react';
import type {FundWork} from './api';
import {actorLabel,readableDate} from './presentation';

type Event=Record<string,unknown>;
const title=(value:unknown)=>String(value??'Saved update').replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
const routine=new Set(['processing_started','processing_completed','fund_review_completed','extraction_completed']);
export function orderedEvents(events:Event[]){return events.map((event,index)=>({event,index})).sort((a,b)=>{
 const time=(e:Event)=>Date.parse(String(e.at??e.timestamp??e.created_at??''))||0;
 return time(b.event)-time(a.event)||b.index-a.index;
}).map(({event})=>event);}
export function materialEvent(event:Event){const detail=event.detail as Event|undefined;return !routine.has(String(event.event??event.action??event.kind))||['FAILED','BLOCKED'].includes(String(detail?.status));}
export function ReviewHistory({events,work}:{events:Event[];work:FundWork}){
 const [all,setAll]=useState(false);const sorted=orderedEvents(events);const visible=all?sorted:sorted.filter(materialEvent);
 return <section><div className="fr-row fr-history-heading"><h3>{all?'Complete activity':'Recent material changes'}</h3><button className="fr-text-button" onClick={()=>setAll(!all)}>{all?'Show material changes':'Show complete activity'}</button></div><p className="fr-muted">Newest first. Complete activity retains processing, failures and earlier decisions.</p><div className="fr-history">{visible.map((event,index)=>{const detail=event.detail as Event|undefined;const action=String(event.event??event.action??event.kind??'');return <article key={index}><span className="fr-history-dot"/><div><h3>{action==='task_updated'&&detail?.action?title(detail.action):title(action)}</h3><p>{String(detail?.reason??event.reason??event.note??detail?.filename??(detail?.status?'Processing '+title(detail.status):'Update recorded'))}</p>{Boolean(detail?.filename&&detail.reason)&&<p>{String(detail?.filename)}</p>}<small>{String(event.actor_name??actorLabel(event.actor_id,work))}{readableDate(event.at??event.timestamp)?' · '+readableDate(event.at??event.timestamp):''}{event.version?' · Version '+String(event.version):''}</small></div></article>})}{!visible.length&&<p>No material changes recorded yet. Open complete activity for processing details.</p>}</div></section>;
}
