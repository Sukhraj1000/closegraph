import { Accordion, AccordionItem, AccordionTrigger, AccordionContent, Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui';
import { DocumentPreview, DownloadLink } from '../../components/closegraph/DocumentPreview';
import { PdfEvidence } from '../../components/closegraph/PdfEvidence';
import { sourceOf, type Fact, type PackSnapshot, type Source } from '../../lib/model';

type SourceEntry = [string, Source];
const documentKey = ([id, source]: SourceEntry) => String(source.document_version_id ?? id) + ':' + String(source.source_id ?? id);
function locationKey(locator: Source['locator']): string | undefined {
 if (!locator) return undefined;
 if (typeof locator === 'string') return locator;
 const kind = locator.kind;
 if (kind === 'xlsx' || (locator.sheet && locator.cell)) return JSON.stringify(['xlsx', locator.sheet ?? locator.sheet_name, locator.cell ?? locator.coordinate]);
 if (kind === 'csv') return JSON.stringify(['csv', locator.row, locator.column]);
 if (kind === 'pdf') return JSON.stringify(['pdf', locator.original_page ?? locator.page, locator.coordinate_system, locator.bbox]);
 return JSON.stringify(Object.entries(locator).filter(([,value]) => value != null).sort(([a],[b]) => a.localeCompare(b)));
}
function factOccurrence(pack: PackSnapshot, fact?: Fact): SourceEntry | undefined {
 if (!fact || !pack.evidence) return undefined;
 const citation = sourceOf(fact), entries = Object.entries(pack.evidence);
 // Legacy story references name a source role. Keep that source's own content
 // and citation together; never overlay a different fact locator onto its rows.
 if (!citation.document_version_id) return entries.find(([id]) => id === citation.source_id);
 const sameDocument = entries.filter(([,source]) => source.document_version_id === citation.document_version_id &&
  (!citation.content_hash || !source.content_hash || source.content_hash === citation.content_hash));
 const location = locationKey(citation.locator);
 const exact = sameDocument.filter(([,source]) => location ? locationKey(source.locator) === location : Array.isArray(source.fact_ids) && source.fact_ids.includes(fact.fact_id));
 const anchored=exact.find(([id]) => id === citation.source_id);
 if(anchored)return anchored;
 const bound=exact.filter(([,source]) => Array.isArray(source.fact_ids) && source.fact_ids.includes(fact.fact_id));
 return exact.length===1?exact[0]:bound.length===1?bound[0]:undefined;
}
export function sourceEntries(pack:PackSnapshot, fact?:Fact):SourceEntry[] {
 if(pack.evidence){
  const documents=new Map<string,SourceEntry>();
  const boundRoles=new Set(Object.entries(pack.evidence).filter(([,source])=>Array.isArray(source.fact_ids)).map(([id,source])=>source.source_id??id));
  const entries=Object.entries(pack.evidence).filter(([id,source])=>Array.isArray(source.fact_ids)||!boundRoles.has(source.source_id??id)).sort((a,b)=>Number(Array.isArray(b[1].fact_ids))-Number(Array.isArray(a[1].fact_ids)));
  for(const entry of entries){const key=documentKey(entry);if(!documents.has(key))documents.set(key,entry);}
  const occurrence=factOccurrence(pack,fact),citation=fact?sourceOf(fact):{};
  return [...documents.values()].map<SourceEntry>(([id,source])=>{
   if(occurrence && documentKey([id,source])===documentKey(occurrence))return [id,occurrence[1]];
   if(!occurrence && citation.document_version_id && source.document_version_id===citation.document_version_id){
    // Only document-level metadata is safe when the cited occurrence is missing.
    // In particular, another cell's preview_rows must not accompany this locator.
    return [id,{document_name:source.document_name,filename:source.filename,media_type:source.media_type,...citation,source_id:source.source_id??citation.source_id}];
   }
   return [id,source];
  });
 }
 const sources = new Map<string,Source>();
 pack.facts.forEach(f=>{const s=sourceOf(f);if(s.source_id)sources.set(s.source_id,s);});
 return [...sources.entries()];
}
export function sourceTabForFact(pack:PackSnapshot,fact:Fact):string|undefined {
 const citation=sourceOf(fact),occurrence=factOccurrence(pack,fact),entries=sourceEntries(pack);
 if(occurrence)return entries.find(entry=>documentKey(entry)===documentKey(occurrence))?.[0];
 if(citation.document_version_id)return entries.find(([,source])=>source.document_version_id===citation.document_version_id)?.[0]??'citation:'+citation.document_version_id;
 return entries.find(([id,source])=>id===citation.source_id||source.source_id===citation.source_id)?.[0];
}
export const sourceName=(id:string,s:Source)=>s.document_name ?? s.filename ?? ({rule:'Fee rule','fee-rule':'Fee rule',capital:'Capital',original:'Original pack','reporting-evidence':'Reporting evidence'}[id] ?? id);
export function SourceEvidence({pack,fact,selectedSource,onSelectSource,onOpenDocument,synthetic=false}:{pack:PackSnapshot;fact?:Fact;selectedSource?:string;onSelectSource?:(source:string)=>void;onOpenDocument?:(document:string)=>void;synthetic?:boolean}) {
 const entries=sourceEntries(pack,fact), known=new Set(entries.map(([id,s])=>s.source_id??id));
 const sources:[string,Source][]=[...entries];
 for(const [id,label] of [['fee-rule','Fee rule'],['capital','Capital'],['original','Original pack']]) if(!known.has(id) && !(id==='fee-rule'&&known.has('rule'))) sources.push([id,{document_name:label,status:'UNAVAILABLE'}]);
 const citation=fact?sourceOf(fact):{};
 if(typeof citation.document_version_id==='string'&&!sources.some(([,s])=>s.document_version_id===citation.document_version_id))sources.push(['citation:'+citation.document_version_id,{...citation,document_name:String(citation.document_name??'Cited document version')}]);
 const selectedOccurrence=selectedSource&&pack.evidence?.[selectedSource];
 const selectedTab=selectedSource&&sources.some(([id])=>id===selectedSource)?selectedSource:selectedOccurrence?sources.find(entry=>documentKey(entry)===documentKey([selectedSource!,selectedOccurrence]))?.[0]:undefined;
 const initial=selectedTab??(fact?sourceTabForFact(pack,fact):undefined)??sources[0]?.[0];
 return <section aria-label="Supporting documents"><h2>Check the source</h2><Tabs value={initial} onValueChange={onSelectSource}><TabsList aria-label="Source document">{sources.map(([id,s])=><TabsTrigger value={id} key={id}>{({rule:'Fee rule','fee-rule':'Fee rule',capital:'Capital',original:'Original pack','reporting-evidence':'Reporting evidence'} as Record<string,string>)[s.source_id??id]??sourceName(id,s)}</TabsTrigger>)}</TabsList>{sources.map(([id,s])=>{

 const unavailable=s.status==='UNAVAILABLE'||s.status==='MISSING';
 const exact=s;
 const download='/api/packs/'+encodeURIComponent(pack.pack_id)+(typeof exact.document_version_id==='string'?'/documents/'+encodeURIComponent(exact.document_version_id):'/evidence/'+encodeURIComponent(id))+'/download';
 const pdf=exact.media_type==='application/pdf'||String(exact.filename??exact.document_name??'').toLowerCase().endsWith('.pdf')||(typeof exact.locator==='object'&&exact.locator?.kind==='pdf');
 return <TabsContent key={id} value={id}><DocumentPreview title={sourceName(id,s)} context={synthetic?'Synthetic source document':String(s.filename??s.document_name??'Original source')} source={exact} stale={pack.freshness==='STALE'} unavailable={unavailable?'This source is unavailable. Add the required evidence and rerun checks. No substitute values are shown.':undefined}/>{!unavailable&&!synthetic&&pdf&&<PdfEvidence url={download} source={exact}/>} {!unavailable&&!synthetic&&<div className="source-actions"><DownloadLink onInspect={()=>{if(typeof exact.document_version_id==='string')onOpenDocument?.(exact.document_version_id);}} url={download} label="Inspect original bytes"/></div>}</TabsContent>;
 })}</Tabs><Accordion type="multiple" className="accordion"><AccordionItem value="observations"><AccordionTrigger>Source and extraction details</AccordionTrigger><AccordionContent className="accordion-body">{fact&&<p>Original value: {String(fact.raw_value??'Unavailable')} · scale: {String(fact.raw_scale??'Unknown')} · {fact.currency} · {fact.period} · {fact.entity_id}</p>}<h3>Canonical extraction provenance</h3>{pack.extraction_observations?.length?pack.extraction_observations.map((observation,i)=><div className="record" key={'extraction-'+i}>{Object.entries(observation).map(([key,value])=><p key={key}><strong>{key.replaceAll('_',' ')}</strong> {typeof value==='object'?JSON.stringify(value):String(value)}</p>)}</div>):<p>No canonical parser observation was supplied. Disabled or unavailable readers have not provided corroboration.</p>}<h3>Reader comparison</h3>{pack.observations?.length ? pack.observations.map((observation,i)=><div className="record" key={i}>{Object.entries(observation).map(([key,value])=><p key={key}><strong>{key.replaceAll('_',' ')}</strong> {typeof value==='object'?JSON.stringify(value):String(value)}</p>)}</div>):<p>No parser observations were supplied for this snapshot. A second reader not run is not agreement.</p>}<p>Reader scores describe their recorded source and method; they do not guarantee correctness. Original observations remain in the evidence history.</p></AccordionContent></AccordionItem></Accordion></section>;
}
