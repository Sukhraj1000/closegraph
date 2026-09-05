import type { Page } from '@playwright/test';
import { test, expect, attachLocalSurfaces } from './fixtures';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

function setting(name:string){const value=process.env[name];if(!value)throw new Error(name+' is required for the isolated evidence journey.');return value;}
async function login(page:Page,role:'PREPARER'|'REVIEWER'){
 await page.goto((process.env.CLOSEGRAPH_UI_URL??'http://127.0.0.1:24273')+'/#collections');
 await page.getByRole('textbox',{name:'Username',exact:true}).fill(setting('CLOSEGRAPH_TEST_'+role+'_USERNAME'));
 await page.getByLabel('Password',{exact:true}).fill(setting('CLOSEGRAPH_TEST_'+role+'_PASSWORD'));
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByRole('navigation',{name:'Workspace'}).getByRole('button',{name:'Collections',exact:true})).toHaveAttribute('aria-current','page');
}
async function snapshot(page:Page,id:string){return page.evaluate(async id=>{const response=await fetch('/api/collections/'+encodeURIComponent(id));if(!response.ok)throw new Error(await response.text());return response.json();},id);}
async function mutation(page:Page,method:string,path:string,action:()=>Promise<unknown>){
 const result=page.waitForResponse(response=>response.request().method()===method&&new URL(response.url()).pathname===path);
 await action();const response=await result;expect(response.ok(),await response.text()).toBe(true);return response.json();
}
async function refresh(page:Page,id:string){
 const response=page.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname==='/api/collections/'+id);
 await page.getByRole('button',{name:'Refresh',exact:true}).click();const result=await response;expect(result.ok(),await result.text()).toBe(true);
 const current=await result.json();await expect(page.getByRole('button',{name:'Refresh',exact:true})).toBeEnabled();return current;
}
async function settled(page:Page,id:string,minVersion:number){
 await expect.poll(async()=>{const value=await snapshot(page,id);return value.version>=minVersion&&!['QUEUED','PROCESSING'].includes(value.status);},{timeout:90000}).toBe(true);
 const value=await refresh(page,id);expect(value.version).toBeGreaterThanOrEqual(minVersion);expect(value.status).not.toMatch(/QUEUED|PROCESSING/);
 await expect(page.getByText('Reading this version.',{exact:false})).toHaveCount(0);return value;
}
async function tab(page:Page,name:string){await page.getByRole('navigation',{name:'Collection navigation'}).getByRole('button',{name,exact:true}).click();}
async function chooseCollection(page:Page,title:string){
 const button=page.getByRole('complementary',{name:'Collections'}).getByRole('button').filter({has:page.getByText(title,{exact:true})});
 await button.click();await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
}
async function openDetails(page:Page,label:string){
 const summary=page.locator('summary').filter({hasText:label});await expect(summary).toHaveCount(1);
 if(!await summary.evaluate(element=>element.parentElement?.hasAttribute('open')))await summary.click();
}
async function reviewHeader(page:Page,id:string){
 await tab(page,'Documents');
 await page.getByRole('button',{name:/row 1: Identifier$/}).click();
 await page.getByRole('combobox',{name:'Action',exact:true}).selectOption({label:'Use selected row as headers'});
 await page.getByRole('textbox',{name:'Reason and source evidence',exact:true}).fill('Compared the original CSV. The first row contains field labels and is excluded from the transaction data.');
 await mutation(page,'POST','/api/collections/'+id+'/edits',()=>page.getByRole('button',{name:'Save extraction decision',exact:true}).click());
 await expect(page.getByRole('button',{name:'Save extraction decision',exact:true})).toBeEnabled();
 await mutation(page,'POST','/api/collections/'+id+'/accept',()=>page.getByRole('button',{name:'Accept this extraction',exact:true}).click());
 await expect(page.getByRole('button',{name:'Extraction accepted',exact:true})).toBeDisabled();
 await expect(page.getByRole('columnheader',{name:'Identifier',exact:true})).toBeVisible();
 await expect(page.getByRole('columnheader',{name:'Amount',exact:true})).toBeVisible();
}
async function addCheck(page:Page,id:string,kind:'evidence'|'total',documentTitle:string,ownerLabel:string){
 await tab(page,'Overview');await openDetails(page,'Add a required check');
 await page.getByRole('textbox',{name:'Check name',exact:true}).fill(kind==='evidence'?'March statement is present':'March amounts match expected total');
 await page.getByRole('combobox',{name:'What should be checked?',exact:true}).selectOption({label:kind==='evidence'?'Document is present and current':'Total matches an expected amount'});
 await page.getByRole('combobox',{name:'Document',exact:true}).selectOption({label:documentTitle});
 if(kind==='total'){
  await page.getByRole('combobox',{name:'Amount field',exact:true}).selectOption({label:'Amount'});
  await page.getByRole('textbox',{name:'Expected total',exact:true}).fill('20.30');
  await page.getByRole('textbox',{name:'Allowed difference',exact:true}).fill('0');
 }
 await page.getByRole('textbox',{name:'Required reporting period',exact:true}).fill('March 2026');
 await page.getByRole('combobox',{name:'Responsible team',exact:true}).selectOption({label:'Accountant'});
 await page.getByRole('combobox',{name:'Responsible person',exact:true}).selectOption({label:ownerLabel});
 await mutation(page,'PUT','/api/collections/'+id+'/requirements',()=>page.getByRole('button',{name:'Add check',exact:true}).click());
 await expect(page.getByRole('button',{name:'Run checks',exact:true})).toBeEnabled();
}
async function runChecks(page:Page,id:string){
 await tab(page,'Overview');
 const current=await mutation(page,'POST','/api/collections/'+id+'/evaluate',()=>page.getByRole('button',{name:'Run checks',exact:true}).click());
 const checked=await settled(page,id,current.version);await expect(page.getByRole('button',{name:'Run checks',exact:true})).toBeEnabled();return checked;
}
async function createOutput(page:Page,id:string){
 await tab(page,'Outputs');
 // Every choice uses a visible field label; JSON and internal identifiers are not edited.
 const amountRow=page.locator('.evidence-mapping-row').filter({has:page.getByRole('checkbox',{name:'Amount',exact:true})});
 await amountRow.getByRole('combobox',{name:'Read as',exact:true}).selectOption({label:'Number'});
 await amountRow.getByRole('combobox',{name:'Number written as',exact:true}).selectOption({label:'1234.56'});
 const queued=await mutation(page,'POST','/api/collections/'+id+'/process',()=>page.getByRole('button',{name:'Create output from these fields',exact:true}).click());
 expect(queued.status).toBe('QUEUED');
 const current=await settled(page,id,queued.version);expect(current.status,JSON.stringify(current.issues)).toBe('READY_FOR_REVIEW');
 await expect(page.getByRole('button',{name:'Export CSV',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'Approve exact output',exact:true})).toHaveCount(0);return current;
}
async function approveAndDownload(page:Page,id:string,amount:string,artifact:(name:string)=>string,prefix:string){
 await refresh(page,id);await tab(page,'Outputs');
 const draftEvent=page.waitForEvent('download');await page.getByRole('link',{name:'Inspect draft CSV',exact:true}).click();const draft=await draftEvent;
 expect(await draft.failure()).toBeNull();await draft.saveAs(artifact(prefix+'-draft.csv'));
 const rows=csvRows(artifact(prefix+'-draft.csv'));expect(rows).toEqual([['Identifier','Amount'],['A','12.20'],['B',amount]]);
 await page.getByRole('textbox',{name:'Independent review reason',exact:true}).fill('Inspected the original statement, the required checks and this exact CSV. The two expected records and revised amount agree with the reviewed source.');
 await page.getByRole('checkbox',{name:/I inspected the source evidence/}).check();
 await mutation(page,'POST','/api/collections/'+id+'/review',()=>page.getByRole('button',{name:'Approve exact output',exact:true}).click());
 await expect(page.getByRole('button',{name:'Export CSV',exact:true})).toBeEnabled();
 await mutation(page,'POST','/api/collections/'+id+'/exports',()=>page.getByRole('button',{name:'Export CSV',exact:true}).click());
 const link=page.getByRole('link',{name:/^Download .*csv$/});await expect(link).toBeVisible();
 const downloadEvent=page.waitForEvent('download');await link.click();const download=await downloadEvent;
 expect(await download.failure()).toBeNull();await download.saveAs(artifact(prefix+'-approved.csv'));
 expect(readFileSync(artifact(prefix+'-approved.csv')).equals(readFileSync(artifact(prefix+'-draft.csv')))).toBe(true);
 expect(csvRows(artifact(prefix+'-approved.csv'))).toEqual([['Identifier','Amount'],['A','12.20'],['B',amount]]);
 const current=await snapshot(page,id);expect(current.status).toBe('APPROVED');return current;
}
function csvRows(filename:string){return readFileSync(filename,'utf8').replace(/^\uFEFF/,'').trim().split(/\r?\n/).map(row=>row.split(',').map(cell=>cell.replace(/^"|"$/g,'')));}

test('documents → named requirements → simple mapping → independent approval → revised evidence → comparison → corrected check → exact download',async({browser})=>{
 test.setTimeout(360000);
 const artifact=(name:string)=>test.info().outputPath(name);mkdirSync(test.info().outputDir,{recursive:true});
 const preparerContext=await browser.newContext({acceptDownloads:true,viewport:{width:1500,height:1000}});
 const managerContext=await browser.newContext({acceptDownloads:true,viewport:{width:1500,height:1000}});
 await attachLocalSurfaces(preparerContext);await attachLocalSurfaces(managerContext);
 const page=await preparerContext.newPage(),manager=await managerContext.newPage();
 try{
  await login(page,'PREPARER');
  const title='Synthetic evidence journey '+Date.now();
  await page.getByRole('textbox',{name:'Name',exact:true}).fill(title);
  const created=await mutation(page,'POST','/api/collections',()=>page.getByRole('button',{name:'Create collection',exact:true}).click()),id=created.id;
  await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
  const csv=(amount:string)=>({name:'bank-statement.csv',mimeType:'text/csv',buffer:Buffer.from('Identifier,Amount\nA,12.20\nB,'+amount+'\n')});
  await page.getByLabel('Files to add',{exact:true}).setInputFiles(csv('8.10'));
  await page.getByRole('textbox',{name:'Reporting period',exact:true}).fill('March 2026');
  const uploaded=await mutation(page,'POST','/api/collections/'+id+'/sources',()=>page.getByRole('button',{name:'Add 1 document',exact:true}).click());
  let current=await settled(page,id,uploaded.version);expect(current.documents).toHaveLength(1);expect(current.datasets.filter((d:{kind:string})=>d.kind==='extraction')).toHaveLength(1);
  const logicalDocumentId=current.documents[0].id,originalSourceId=current.documents[0].current_revision_id,preparerActor=current.access.actor_id;
  await reviewHeader(page,id);

  await login(manager,'REVIEWER');await chooseCollection(manager,title);
  const managerState=await snapshot(manager,id);expect(managerState.access.can_manage).toBe(true);expect(managerState.access.can_review).toBe(true);expect(managerState.access.actor_id).not.toBe(preparerActor);
  const owner=managerState.members.find((member:{actor_id:string})=>member.actor_id===preparerActor);expect(owner?.party).toBe('accountant');expect(owner?.display_name).toBeTruthy();
  await addCheck(manager,id,'evidence',managerState.documents[0].title,owner.display_name);
  await addCheck(manager,id,'total',managerState.documents[0].title,owner.display_name);
  const passed=await runChecks(manager,id);expect(passed.check_results).toHaveLength(2);expect(passed.check_results.every((check:{status:string})=>check.status==='PASS')).toBe(true);

  await refresh(page,id);const firstReady=await createOutput(page,id);
  writeFileSync(artifact('initial-ready.json'),JSON.stringify(firstReady,null,2));
  await approveAndDownload(manager,id,'8.10',artifact,'initial');
  await manager.screenshot({path:artifact('initial-approved-output.png'),fullPage:true});

  await refresh(page,id);await tab(page,'Documents');
  await page.getByRole('button',{name:'Upload new version',exact:true}).click();
  await page.getByLabel('Replacement file',{exact:true}).setInputFiles(csv('8.40'));
  await page.getByRole('textbox',{name:'What changed?',exact:true}).fill('The supplied revision corrects record B from 8.10 to 8.40; the expected total is now 20.60.');
  const revised=await mutation(page,'POST','/api/collections/'+id+'/sources',()=>page.getByRole('button',{name:'Save new version',exact:true}).click());
  current=await settled(page,id,revised.version);
  expect(current.status).not.toBe('APPROVED');expect(current.documents).toHaveLength(1);expect(current.documents[0].id).toBe(logicalDocumentId);expect(current.documents[0].revisions).toHaveLength(2);expect(current.documents[0].current_revision_id).not.toBe(originalSourceId);
  await reviewHeader(page,id);
  await tab(page,'Review changes');
  await expect(page.getByRole('columnheader',{name:'Previous version',exact:true})).toBeVisible();
  await expect(page.getByText('8.10',{exact:true})).toBeVisible();await expect(page.getByText('8.40',{exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Open previous original',exact:true})).toHaveAttribute('href','/api/collections/'+id+'/sources/'+originalSourceId+'/download');
  await page.screenshot({path:artifact('document-revision-comparison.png'),fullPage:true});

  await refresh(manager,id);const failed=await runChecks(manager,id);
  const totalRequirement=failed.requirements.find((requirement:{kind:string})=>requirement.kind==='total');
  expect(failed.check_results.find((check:{requirement_id:string})=>check.requirement_id===totalRequirement.id)?.status).toBe('FAIL');
  writeFileSync(artifact('revised-check-failed.json'),JSON.stringify(failed,null,2));
  const checkCard=manager.locator('.evidence-check-list .record').filter({hasText:'March amounts match expected total'});
  await expect(checkCard.getByText('Check failed',{exact:true})).toBeVisible();
  await checkCard.getByRole('button',{name:'Edit check',exact:true}).click();
  await manager.getByRole('textbox',{name:'Expected total',exact:true}).fill('20.60');
  await mutation(manager,'PUT','/api/collections/'+id+'/requirements',()=>manager.getByRole('button',{name:'Save check changes',exact:true}).click());
  const corrected=await runChecks(manager,id);expect(corrected.check_results.every((check:{status:string})=>check.status==='PASS')).toBe(true);

  await refresh(page,id);const finalReady=await createOutput(page,id);
  expect(finalReady.datasets.find((d:{kind:string})=>d.kind==='output')?.stale).not.toBe(true);
  const approved=await approveAndDownload(manager,id,'8.40',artifact,'revised');
  expect(readFileSync(artifact('revised-approved.csv')).equals(readFileSync(artifact('initial-approved.csv')))).toBe(false);
  writeFileSync(artifact('revised-approved.json'),JSON.stringify(approved,null,2));
  await manager.screenshot({path:artifact('revised-approved-output.png'),fullPage:true});
 }finally{await preparerContext.close();await managerContext.close();}
});
