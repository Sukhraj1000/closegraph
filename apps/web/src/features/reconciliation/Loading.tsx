import {BatmanSprite} from '../../components/closegraph/Batman';
export function Loading({text}:{text:string}){return <div className="reconcile-loading" role="status"><span className="batman-loader-track" aria-hidden="true"><BatmanSprite/></span><span>{text}<small>You can leave this page. Saved processing continues.</small></span></div>;}
