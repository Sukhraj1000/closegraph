import { useEffect,useRef,useState } from 'react';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { safeDownloadURL,type Source } from '../../lib/model';
import { pdfHighlight,type PdfHighlight } from '../../lib/pdf-highlight';
export function PdfEvidence({url,source}:{url:string;source:Source}) {
 const canvas=useRef<HTMLCanvasElement>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[pageText,setPageText]=useState(''),[highlight,setHighlight]=useState<PdfHighlight|null>(null);
 const locator=source.locator&&typeof source.locator==='object'?source.locator:{};
 const originalPage=Number(locator.original_page),safe=safeDownloadURL(url);
 useEffect(()=>{
  const controller=new AbortController();let live=true,document:import('pdfjs-dist').PDFDocumentProxy|undefined,task:import('pdfjs-dist').PDFDocumentLoadingTask|undefined;
  setLoading(true);setError('');setPageText('');setHighlight(null);
  async function render(){
   try{
    if(!safe||!Number.isInteger(originalPage)||originalPage<1)throw new Error('The original PDF page citation is unavailable.');
    const response=await fetch(safe,{credentials:'same-origin',signal:controller.signal,redirect:'error'});
    if(!response.ok)throw new Error('The original PDF could not be loaded. Your source access may have changed.');
    if(Number(response.headers.get('content-length'))>20*1024*1024)throw new Error('This PDF exceeds the 20 MB inline preview limit. Inspect the original download.');
    const data=new Uint8Array(await response.arrayBuffer());
    if(data.byteLength>20*1024*1024)throw new Error('This PDF exceeds the 20 MB inline preview limit. Inspect the original download.');
    const pdfjs=await import('pdfjs-dist');if(!live)return;
    pdfjs.GlobalWorkerOptions.workerSrc=workerUrl;
    task=pdfjs.getDocument({data,useSystemFonts:true,stopAtErrors:true});
    document=await task.promise;if(!live)return;
    if(originalPage>document.numPages)throw new Error('The cited original page is outside this PDF.');
    const page=await document.getPage(originalPage),natural=page.getViewport({scale:1}),viewport=page.getViewport({scale:Math.min(2,1000/natural.width)});
    const target=canvas.current;if(!live||!target)return;
    target.width=Math.ceil(viewport.width);target.height=Math.ceil(viewport.height);
    const context=target.getContext('2d');if(!context)throw new Error('The browser cannot render a PDF canvas.');
    setHighlight(pdfHighlight(locator,page.view,viewport.transform,viewport.width,viewport.height));
    await page.render({canvas:target,canvasContext:context,viewport}).promise;
    const content=await page.getTextContent();if(live)setPageText(content.items.map(item=>'str' in item?item.str:'').join(' '));
    if(live)setLoading(false);
   }catch(error){if(live&&!controller.signal.aborted){setError((error as Error).message);setLoading(false);}}
  }
  void render();
  return()=>{live=false;controller.abort();void task?.destroy();};
 },[safe,originalPage,JSON.stringify(locator)]);
 return <figure className="pdf-evidence"><figcaption>Original PDF · page {Number.isInteger(originalPage)?originalPage:'unavailable'}</figcaption>{loading&&<p role="status">Loading the cited original page…</p>}{error&&<p role="alert">{error}</p>}<div className="pdf-page" hidden={Boolean(error)}><canvas ref={canvas} role="img" aria-label={'Original PDF page '+originalPage+'. The cited source region is outlined when exact coordinates are available.'}/>{highlight&&!loading&&<span className="pdf-highlight" aria-hidden style={{left:highlight.left+'%',top:highlight.top+'%',width:highlight.width+'%',height:highlight.height+'%'}}/>}</div>{!loading&&!error&&<p className="caption">{highlight?'Outlined area: the exact cited region on the original page.':'This citation has no supported precise region. Inspect the full original page; no position has been guessed.'}</p>}{!loading&&!error&&<details><summary>Read original page text</summary><p>{pageText||'No embedded text is available on this original page. Inspect the rendered page.'}</p></details>}</figure>;
}
