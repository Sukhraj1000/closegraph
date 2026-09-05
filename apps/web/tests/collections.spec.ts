import type { Page } from '@playwright/test';
import { test, expect, attachLocalSurfaces } from './fixtures';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
function setting(name:string){const value=process.env[name];if(!value)throw new Error(name+' is required for the real collection journey.');return value;}
async function login(page:Page,role:'PREPARER'|'REVIEWER'){
 await page.goto((process.env.CLOSEGRAPH_UI_URL??'http://127.0.0.1:24173')+'/#collections');
 await page.getByRole('textbox',{name:'Username',exact:true}).fill(setting('CLOSEGRAPH_TEST_'+role+'_USERNAME'));
 await page.getByLabel('Password',{exact:true}).fill(setting('CLOSEGRAPH_TEST_'+role+'_PASSWORD'));
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByRole('navigation',{name:'Workspace'}).getByRole('button',{name:'Collections',exact:true})).toHaveAttribute('aria-current','page');
}
async function snapshot(page:Page,id:string){return page.evaluate(async id=>{const response=await fetch('/api/collections/'+encodeURIComponent(id));if(!response.ok)throw new Error(await response.text());return response.json();},id);}
async function settled(page:Page,id:string,minVersion=1){
 await expect.poll(async()=>{const state=await snapshot(page,id);return state.version>=minVersion&&!['QUEUED','PROCESSING'].includes(state.status);},{timeout:60000}).toBe(true);
 const refreshed=page.waitForResponse(r=>r.request().method()==='GET'&&r.url().endsWith('/api/collections/'+id));
 await page.getByRole('button',{name:'Refresh',exact:true}).click();const response=await refreshed;expect(response.ok(),await response.text()).toBe(true);
 const state=await response.json();expect(state.version).toBeGreaterThanOrEqual(minVersion);expect(state.status).not.toMatch(/QUEUED|PROCESSING/);
 await expect(page.getByText('Processing this revision.',{exact:false})).toHaveCount(0);
}
async function saveHeader(page:Page,table:{id:string;columns:{key:string;label:string}[]},firstValue:string){
 await page.getByRole('combobox',{name:'Extracted table',exact:true}).selectOption(table.id);
 await page.getByRole('button',{name:new RegExp('row 1: '+firstValue+'$')}).click();
 await page.getByRole('combobox',{name:'Action',exact:true}).selectOption('set_header');
 await page.getByRole('textbox',{name:'Reason and source evidence',exact:true}).fill('The original CSV first row contains field labels; retain it in history and exclude it from data rows.');
 const saved=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/edits'));
 await page.getByRole('button',{name:'Save extraction decision',exact:true}).click();const response=await saved;expect(response.ok(),await response.text()).toBe(true);
 await expect(page.getByRole('button',{name:'Save extraction decision',exact:true})).toBeEnabled();
 const accepted=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/accept'));
 await page.getByRole('button',{name:'Accept this extraction',exact:true}).click();const approval=await accepted;expect(approval.ok(),await approval.text()).toBe(true);
 await expect(page.getByRole('button',{name:'Extraction accepted',exact:true})).toBeDisabled();
}
test('arbitrary CSV tables → explicit header review → deterministic rules → independent draft inspection → exact reviewed export',async({browser})=>{
 test.setTimeout(210000);
 const artifact=(name:string)=>test.info().outputPath(name);mkdirSync(test.info().outputDir,{recursive:true});
 const preparerContext=await browser.newContext({acceptDownloads:true,viewport:{width:1500,height:1000}}),reviewerContext=await browser.newContext({acceptDownloads:true,viewport:{width:1500,height:1000}});
 await attachLocalSurfaces(preparerContext);await attachLocalSurfaces(reviewerContext);
 const page=await preparerContext.newPage(),reviewPage=await reviewerContext.newPage();
 try{
  await login(page,'PREPARER');const title='Synthetic collection '+Date.now();
  await page.getByRole('textbox',{name:'Name',exact:true}).fill(title);
  const created=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/collections'));
  await page.getByRole('button',{name:'Create collection',exact:true}).click();const createResponse=await created;expect(createResponse.ok(),await createResponse.text()).toBe(true);const collection=await createResponse.json(),id=collection.id;
  await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
  await page.getByLabel('Source files to upload',{exact:true}).setInputFiles([{name:'transactions-different-format.csv',mimeType:'text/csv',buffer:Buffer.from('Identifier,Amount\nA,12.20\nB,8.10\n')},{name:'reference-data.csv',mimeType:'text/csv',buffer:Buffer.from('Identifier,Category\nA,North\nB,South\n')}]);
  await page.getByRole('button',{name:'Upload 2 files',exact:true}).click();
  await expect.poll(async()=>(await snapshot(page,id)).sources.length,{timeout:45000}).toBe(2);await settled(page,id);
  let current=await snapshot(page,id);expect(current.datasets.length).toBe(2);
  for(const table of current.datasets)await saveHeader(page,table,'Identifier');
  current=await snapshot(page,id);expect(current.datasets.every((d:{accepted:boolean})=>d.accepted)).toBe(true);
  const transactions=current.datasets.find((d:{source_id:string})=>d.source_id===current.sources.find((s:{filename:string})=>s.filename==='transactions-different-format.csv').id),reference=current.datasets.find((d:{id:string})=>d.id!==transactions.id);
  await page.getByRole('button',{name:/Transformation$/}).click();
  const recipe={version:1,steps:[{id:'selected',op:'select',input:transactions.table_id,columns:['c1','c2']},{id:'matched',op:'lookup',input:'selected',right:reference.table_id,on:[{left:'c1',right:'c1'}],columns:{c2:'category'},how:'left',cardinality:'many_to_one'},{id:'calculated',op:'derive',input:'matched',columns:{doubled:{op:'multiply',args:[{column:'c2'},{literal:'2'}]}}}],output:'calculated',checks:[{type:'required',columns:['c1','c2','category','doubled']},{type:'unique',columns:['c1']},{type:'total',column:'doubled',expected:'40.60',tolerance:'0'}]};
  await page.getByRole('textbox',{name:'Complete recipe',exact:true}).fill(JSON.stringify(recipe,null,2));
  const queuedResponse=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/collections/'+id+'/process'));
  await page.getByRole('button',{name:'Save and transform',exact:true}).click();
  const processResponse=await queuedResponse;expect(processResponse.ok(),await processResponse.text()).toBe(true);
  const queued=await processResponse.json();expect(queued.status).toBe('QUEUED');expect(queued.version).toBeGreaterThan(current.version);
  await settled(page,id,queued.version);
  current=await snapshot(page,id);expect(current.status,JSON.stringify(current.issues)).toBe('READY_FOR_REVIEW');
  writeFileSync(artifact('collection-ready.json'),JSON.stringify(current,null,2));
  await page.getByRole('button',{name:/Output & release/}).click();await expect(page.getByRole('button',{name:'Export CSV',exact:true})).toBeDisabled();expect(await page.getByRole('button',{name:'Approve exact output',exact:true}).count()).toBe(0);
  await page.screenshot({path:artifact('collection-preparer-output.png'),fullPage:true});
  await login(reviewPage,'REVIEWER');await reviewPage.getByRole('complementary',{name:'Collections'}).getByRole('button',{name:new RegExp(title)}).click();await expect(reviewPage.getByRole('heading',{name:title,exact:true})).toBeVisible();await reviewPage.getByRole('button',{name:/Output & release/}).click();
  const draftDownload=reviewPage.waitForEvent('download');await reviewPage.getByRole('link',{name:'Inspect draft CSV',exact:true}).click();const draft=await draftDownload;expect(await draft.failure()).toBeNull();await draft.saveAs(artifact('collection-draft.csv'));
  await reviewPage.getByRole('textbox',{name:'Independent review reason',exact:true}).fill('Inspected the original CSV sources and draft output. Explicit lookup and Decimal doubling match the two source records; total is 40.60.');
  await reviewPage.getByRole('checkbox',{name:/I inspected the source evidence/}).check();await reviewPage.getByRole('button',{name:'Approve exact output',exact:true}).click();await expect(reviewPage.getByRole('button',{name:'Export CSV',exact:true})).toBeEnabled();
  await reviewPage.getByRole('button',{name:'Export CSV',exact:true}).click();const downloadLink=reviewPage.getByRole('link',{name:/^Download .*csv$/});await expect(downloadLink).toBeVisible();const releasedDownload=reviewPage.waitForEvent('download');await downloadLink.click();const released=await releasedDownload;expect(await released.failure()).toBeNull();await released.saveAs(artifact('collection-reviewed.csv'));
  expect(readFileSync(artifact('collection-reviewed.csv')).equals(readFileSync(artifact('collection-draft.csv')))).toBe(true);
  const rows=readFileSync(artifact('collection-reviewed.csv'),'utf8').replace(/^\uFEFF/,'').trim().split(/\r?\n/).map(row=>row.split(',').map(cell=>cell.replace(/^"|"$/g,'')));
  expect(rows.length).toBe(3);expect(rows.slice(1).map(row=>[row[0],Number(row[1]),row[2],Number(row[3])])).toEqual([['A',12.2,'North',24.4],['B',8.1,'South',16.2]]);
  await reviewPage.screenshot({path:artifact('collection-reviewed-output.png'),fullPage:true});writeFileSync(artifact('collection-reviewed.json'),JSON.stringify(await snapshot(reviewPage,id),null,2));
 }finally{await preparerContext.close();await reviewerContext.close();}
});
