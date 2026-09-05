import type { Source } from './model';
export interface PdfHighlight {left:number;top:number;width:number;height:number}
// Canonical locators address the original page. PDF coordinates are projected
// through the page viewport so page rotation and nonzero media-box origins agree.
export function pdfHighlight(locator:Source['locator'],view:number[],transform:number[],width:number,height:number):PdfHighlight|null {
 if(!locator||typeof locator==='string'||!Array.isArray(locator.bbox)||locator.bbox.length!==4)return null;
 const b=locator.bbox.map(Number),[x0,y0,x2,y2]=view,w=x2-x0,h=y2-y0;
 if(!b.every(Number.isFinite)||b[0]>=b[2]||b[1]>=b[3]||w<=0||h<=0)return null;
 let [left,top,right,bottom]=b;
 if(locator.coordinate_system==='normalised-0-1'){if(b.some(n=>n<0||n>1))return null;left*=w;right*=w;top*=h;bottom*=h;}
 else if(!['points-top-left','points-bottom-left'].includes(String(locator.coordinate_system)))return null;
 if(left<0||right>w||top<0||bottom>h)return null;
 const ys=locator.coordinate_system==='points-bottom-left'?[top,bottom]:[h-top,h-bottom];
 const [a,c,b1,d,e,f]=transform;
 const points=[[left,ys[0]],[right,ys[0]],[left,ys[1]],[right,ys[1]]].map(([x,y])=>[a*(x+x0)+b1*(y+y0)+e,c*(x+x0)+d*(y+y0)+f]);
 const xs=points.map(p=>p[0]),py=points.map(p=>p[1]),minX=Math.min(...xs),minY=Math.min(...py);
 return {left:minX/width*100,top:minY/height*100,width:(Math.max(...xs)-minX)/width*100,height:(Math.max(...py)-minY)/height*100};
}
