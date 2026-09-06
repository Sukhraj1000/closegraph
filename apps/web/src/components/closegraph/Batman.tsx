import {useEffect,useState} from 'react';
import './batman.css';
export const BATMAN_VISIT_MS=60_000;
export const BATMAN_VISIT_DURATION_MS=5_600;
export const BATMAN_MOVES=['run','flip','glide','grapple'] as const;
type Move=typeof BATMAN_MOVES[number];

/** Original code-drawn pixel sprite; no remote assets or network calls. */
export function BatmanSprite({className=''}:{className?:string}){
 return <svg className={'batman-sprite '+className} viewBox="0 0 40 48" shapeRendering="crispEdges" aria-hidden="true" focusable="false">
  <g className="batman-cape"><path fill="#0a101c" stroke="#53627b" strokeWidth="1" d="M11 17H29L38 40L31 38L27 43L21 40L16 44L12 39L3 41Z"/><path fill="#202d45" d="M11 20H16L12 38L7 39ZM25 20H29L33 36L28 38Z"/></g>
  <g className="batman-leg left"><path fill="#69778a" d="M13 32H19V41H13Z"/><path fill="#101928" d="M12 39H19V45H9V42H12Z"/></g>
  <g className="batman-leg right"><path fill="#69778a" d="M21 32H27V41H21Z"/><path fill="#101928" d="M21 39H28V42H31V45H21Z"/></g>
  <path fill="#526074" d="M11 18H29V30L26 35H14L11 30Z"/><path fill="#8693a3" d="M14 18H26V29H14Z"/>
  <g className="batman-arm left"><path fill="#68768a" d="M8 20H12V31H8Z"/><path fill="#152039" d="M6 27H12V35H7V32H4V30H6Z"/></g>
  <g className="batman-arm right"><path fill="#68768a" d="M28 20H32V31H28Z"/><path fill="#152039" d="M28 27H34V30H36V32H33V35H28Z"/></g>
  <path fill="#e8bd42" d="M12 30H28V33H12Z"/><path fill="#ffe38b" d="M18 29H22V34H18ZM13 30H15V33H13ZM25 30H27V33H25Z"/>
  <path fill="#f5ce4f" d="M14 21H26V26H14Z"/><path fill="#0b1221" d="M14 22H17V23H18V21H19V23H21V21H22V23H23V22H26L24 25H22L20 27L18 25H16Z"/>
  <path fill="#0c1423" stroke="#66748a" strokeWidth="1" d="M11 1H14L16 7H24L26 1H29V17L25 20H15L11 17Z"/><path fill="#27344c" d="M13 7H16V11H13ZM25 7H27V11H25Z"/>
  <path fill="#edf8ff" d="M14 11H18V13H15ZM22 11H26L25 13H22Z"/><path fill="#d7a77a" d="M15 15H25V18H23V20H17V18H15Z"/><path fill="#795346" d="M18 17H22V18H18Z"/>
 </svg>;
}

export function BatmanPet(){
 const [enabled,setEnabled]=useState(()=>{try{return localStorage.getItem('closegraph.batman')!=='off';}catch{return true;}});
 const [reduced,setReduced]=useState(()=>window.matchMedia?.('(prefers-reduced-motion: reduce)').matches??false);
 const [visit,setVisit]=useState<{move:Move;side:'left'|'right'}|null>(null);
 useEffect(()=>{const query=window.matchMedia?.('(prefers-reduced-motion: reduce)');if(!query)return;const update=()=>setReduced(query.matches);query.addEventListener('change',update);return()=>query.removeEventListener('change',update);},[]);
 useEffect(()=>{
  if(!enabled||reduced){setVisit(null);return;}
  let next:ReturnType<typeof setTimeout>|undefined,finish:ReturnType<typeof setTimeout>|undefined;
  let index=Math.floor(Math.random()*BATMAN_MOVES.length);
  function schedule(){next=setTimeout(()=>{if(document.visibilityState==='hidden')return;setVisit({move:BATMAN_MOVES[index],side:Math.random()<.5?'left':'right'});index=(index+1)%BATMAN_MOVES.length;finish=setTimeout(()=>setVisit(null),BATMAN_VISIT_DURATION_MS);schedule();},BATMAN_VISIT_MS);}
  function visible(){clearTimeout(next);clearTimeout(finish);setVisit(null);if(document.visibilityState!=='hidden')schedule();}
  visible();document.addEventListener('visibilitychange',visible);
  return()=>{clearTimeout(next);clearTimeout(finish);document.removeEventListener('visibilitychange',visible);};
 },[enabled,reduced]);
 function toggle(){const value=!enabled;setEnabled(value);try{localStorage.setItem('closegraph.batman',value?'on':'off');}catch{/* Preference remains available for this visit. */}}
 if(reduced)return null;
 return <><div className="batman-pet-stage" aria-hidden="true">{visit&&<div className={'batman-visit '+visit.side+' move-'+visit.move} data-testid="batman-visit" data-move={visit.move}><span className="batman-rope"/><BatmanSprite/></div>}</div><button className="batman-pet-toggle" type="button" onClick={toggle} aria-label={enabled?'Pause Batman visits':'Resume Batman visits'} title={enabled?'Pause Batman visits':'Resume Batman visits'} aria-pressed={enabled}><BatmanSprite/><span aria-hidden="true">{enabled?'Ⅱ':'▶'}</span></button></>;
}
