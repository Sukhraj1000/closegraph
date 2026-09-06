import {test,expect} from './fixtures';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
test.use({trace:'off'});

test('large public records: inspect every exception, request, correct, revise and independently review',async({page},info)=>{
 const root=process.env.CLOSEGRAPH_PUBLIC_TEST_FILES;
 test.skip(!root,'Supply the local public SEC acceptance directory; no dataset is committed.');
 test.setTimeout(900000);page.setDefaultTimeout(25000);
 const manifest=JSON.parse(readFileSync(join(root!,'manifest.json'),'utf8'));
 let name=process.env.CLOSEGRAPH_DEMO_REUSE_ID?'Public-data demo · filing reference review':'Public-data demo · '+new Date().toISOString().slice(0,19).replace('T',' ');
 const numeric='SEC reordered with missing references.csv';
 const register='SEC filing register.csv';
 const ruleName='Every reported fact belongs to a filing in the register';
 async function login(role:'preparer'|'reviewer'){
  await page.goto('/');await page.getByLabel('Username',{exact:true}).fill(role);
  await page.getByLabel('Password',{exact:true}).fill(process.env[role==='preparer'?'CLOSEGRAPH_TEST_PREPARER_PASSWORD':'CLOSEGRAPH_TEST_REVIEWER_PASSWORD']!);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Recent work',exact:true})).toBeVisible();
 }
 await login('preparer');
 let id=process.env.CLOSEGRAPH_DEMO_REUSE_ID;
 if(!id){
  await page.getByLabel('Reporting pack and supporting documents').setInputFiles([join(root!,numeric),join(root!,register)]);
  await page.getByLabel('Review name',{exact:false}).fill(name);
  const starting=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.endsWith('/fund-review'));
  await page.getByRole('button',{name:'Prepare review brief',exact:true}).click();
  const response=await starting;expect(response.ok(),await response.text()).toBe(true);id=(await response.json()).id;
 }else{
  name=await page.evaluate(async id=>(await(await fetch('/api/collections/'+id)).json()).title,id);
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Recent work',exact:true}).click();
  await page.locator('.fr-recent-list article').filter({hasText:name}).getByRole('button',{name:'Open work'}).click();
 }
 info.annotations.push({type:'isolated-collection',description:id!});
 const state=()=>page.evaluate(async id=>(await(await fetch('/api/collections/'+id)).json()),id!);
 const result=()=>page.evaluate(async id=>(await(await fetch('/api/collections/'+id+'/fund-review/results?limit=500')).json()),id!);
 async function settled(showBrief=true){
  await expect.poll(async()=>(await state()).fund_review?.status,{timeout:420000,intervals:[2000,5000]}).toBe('COMPLETE');
  if(showBrief)await expect(page.getByRole('button',{name:'Download brief',exact:true})).toBeVisible();
 }
 await settled();let r=await result();
 expect(r.coverage.complete).toBe(true);expect(r.summary.row_count).toBeGreaterThan(136000);
 const source=r.tables.find((t:any)=>t.title===numeric),reference=r.tables.find((t:any)=>t.title===register);
 expect(source).toBeTruthy();expect(reference).toBeTruthy();
 let dialog=page.getByRole('dialog',{name:'Checks for this review'});
 if(!(await state()).fund_review.config.checks.length){
  await page.getByRole('button',{name:'Choose checks for this pack',exact:true}).click();
  await dialog.getByRole('button',{name:'Add a check',exact:true}).click();
  await dialog.getByLabel('Give the check a clear name').fill(ruleName);
  await dialog.getByRole('combobox',{name:'Source table',exact:true}).selectOption(source.dataset_id);
  await dialog.getByRole('combobox',{name:'Source column',exact:true}).selectOption(source.columns.find((c:any)=>c.label==='Filing reference').key);
  await dialog.getByRole('combobox',{name:'Reference table',exact:true}).selectOption(reference.dataset_id);
  await dialog.getByRole('combobox',{name:'Reference column',exact:true}).selectOption(reference.columns.find((c:any)=>c.label==='adsh').key);
  await dialog.getByRole('checkbox',{name:/I checked these selections/}).check();
  const saving=page.waitForResponse(res=>res.request().method()==='POST'&&new URL(res.url()).pathname.endsWith('/fund-review'));
  await dialog.getByRole('button',{name:'Save and check',exact:true}).click();expect((await saving).ok()).toBe(true);await settled();
 }
 r=await result();let finding=r.findings.find((f:any)=>f.title===ruleName);
 expect(finding.status).toBe('difference');
 if(!process.env.CLOSEGRAPH_DEMO_REUSE_ID||finding.affected_count===63){
 expect(finding.affected_count).toBe(63);
 await page.screenshot({path:info.outputPath('large-review-63-exceptions.png'),fullPage:true});
 async function openFinding(){await page.locator('.fr-findings .fr-finding').filter({hasText:ruleName}).click();return page.getByRole('dialog',{name:'Finding and supporting evidence'});}
 dialog=await openFinding();
 await dialog.getByRole('button',{name:'View affected records',exact:true}).click();
 const records=dialog.getByRole('region',{name:'All affected records'});
 await expect(records.getByText('63 source records in this finding.',{exact:true})).toBeVisible();
 await expect(records.locator('tbody tr')).toHaveCount(50);
 await records.getByRole('button',{name:'Next affected records'}).click();await expect(records.locator('tbody tr')).toHaveCount(13);
 await records.getByText('Show full record 51',{exact:true}).click();
 await page.screenshot({path:info.outputPath('all-records-page-two.png'),fullPage:true});
 const downloading=page.waitForEvent('download');await records.getByRole('link',{name:'Download all affected records (CSV)'}).click();
 const csv=await downloading;expect(await csv.failure()).toBeNull();await csv.saveAs(info.outputPath('all-63-exceptions.csv'));
 expect(readFileSync(info.outputPath('all-63-exceptions.csv'),'utf8')).toContain('UNRESOLVED TEST FILING');
 await dialog.getByRole('button',{name:'Close panel',exact:true}).click();
 // Record the specific missing-reference request before correcting any source data.
 dialog=await openFinding();const work=await state();const owner=work.members.find((m:any)=>m.party==='account_manager');
 await dialog.getByText('Ask someone to resolve this',{exact:true}).click();
 await dialog.getByLabel('Request owner').selectOption(owner.actor_id);
 await dialog.getByLabel('Request explanation').fill('63 records have the test-corrupted filing reference. Restore each original filing identifier from the unchanged SEC source and upload the corrected revision.');
 await dialog.getByRole('button',{name:'Create request',exact:true}).click();
 await expect(page.getByRole('button',{name:'View supporting finding',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'View supporting finding',exact:true}).click();dialog=page.getByRole('dialog',{name:'Finding and supporting evidence'});
 const first=finding.evidence[0];const sourceRow=first.locator.row;
 const originalRow=manifest.expected.modified_row_count+3-sourceRow;
 const entry=manifest.mutations.find((m:any)=>m.field==='adsh'&&m.row===originalRow);expect(entry).toBeTruthy();
 await dialog.getByRole('button',{name:'Inspect or correct this extraction',exact:true}).first().click();
 dialog=page.getByRole('dialog',{name:'Source documents'});
 await expect(dialog.locator('.collection-cell[aria-pressed="true"]').first()).toBeVisible();
 await expect(dialog.getByLabel('Corrected value',{exact:true})).toBeEnabled();
 await dialog.getByLabel('Corrected value',{exact:true}).fill(entry.before);
 await dialog.getByLabel('Reason and source evidence',{exact:true}).fill('Restore the original SEC filing reference from independently recorded source row '+originalRow+'. Isolated acceptance correction.');
 const correction=page.waitForResponse(res=>res.request().method()==='POST'&&new URL(res.url()).pathname.endsWith('/edits'));
 await dialog.getByRole('button',{name:'Save extraction decision',exact:true}).click();expect((await correction).ok()).toBe(true);
 await dialog.getByRole('button',{name:'Close panel',exact:true}).click();await settled(false);
 r=await result();finding=r.findings.find((f:any)=>f.title===ruleName);expect(finding.affected_count).toBe(62);
 }
 expect(finding.affected_count).toBe(62);
 expect((await state()).tasks.some((t:any)=>t.kind==='fund_review'&&t.status!=='resolved')).toBe(true);
 // Submit the independently restored full revision; same layout, original public values.
 await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Recent work',exact:true}).click();await page.locator('.fr-recent-list article').filter({hasText:name}).getByRole('button',{name:'Open work'}).click();
 await page.getByRole('button',{name:'Documents',exact:true}).click();dialog=page.getByRole('dialog',{name:'Source documents'});
 await dialog.locator('.evidence-document-list button').filter({hasText:numeric}).click();
 await dialog.getByRole('button',{name:'Upload new version',exact:true}).click();
 await dialog.getByLabel('Replacement file',{exact:true}).setInputFiles(join(root!,'revisions',numeric));
 await dialog.getByLabel('What changed?',{exact:true}).fill('Restore all original public SEC field values from the independent ledger; preserve the reordered columns and rows.');
 const upload=page.waitForResponse(res=>res.request().method()==='POST'&&new URL(res.url()).pathname==='/api/collections/'+id+'/sources');
 await dialog.getByRole('button',{name:'Save new version',exact:true}).click();const uploaded=await upload;if(!uploaded.ok()){const current=await state();await info.attach('upload-version-diagnostic',{contentType:'application/json',body:JSON.stringify({expected_version:uploaded.request().postDataJSON().expected_version,version:current.version,history:current.history.map((h:any)=>({version:h.version,event:h.event,actor:h.actor_id,at:h.at}))},null,2)});}expect(uploaded.ok(),uploaded.ok()?undefined:await uploaded.text()).toBe(true);
 await dialog.getByRole('button',{name:'Close panel',exact:true}).click();await settled();
 r=await result();expect(r.findings.find((f:any)=>f.title===ruleName).status).toBe('passed');
 expect((await state()).tasks.filter((t:any)=>t.kind==='fund_review').every((t:any)=>t.status==='resolved')).toBe(true);
 const originalHash=await page.evaluate(async({id,source})=>{const bytes=await(await fetch('/api/collections/'+id+'/sources/'+source+'/download')).arrayBuffer();return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(n=>n.toString(16).padStart(2,'0')).join('');},{id:id!,source:source.source_id});
 expect(originalHash).toBe(createHash('sha256').update(readFileSync(join(root!,numeric))).digest('hex'));
 await page.getByRole('button',{name:'History',exact:true}).click();dialog=page.getByRole('dialog',{name:'Review history'});
 await expect(dialog.getByText('Fixed',{exact:true}).first()).toBeVisible();await page.screenshot({path:info.outputPath('revision-and-request-history.png'),fullPage:true});
 await dialog.getByRole('button',{name:'Close panel',exact:true}).click();
 await page.getByRole('button',{name:'Sign out',exact:true}).click();await login('reviewer');
 await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Recent work',exact:true}).click();await page.locator('.fr-recent-list article').filter({hasText:name}).getByRole('button',{name:'Open work'}).click();
 await page.getByRole('button',{name:'Review and release',exact:true}).click();dialog=page.getByRole('dialog',{name:'Independent review'});
 await dialog.getByLabel('Review notes').fill('Independent test review: every numeric record belongs to the selected SEC filing register. Approval is limited to this reference-membership check.');
 const approval=page.waitForResponse(res=>res.request().method()==='POST'&&new URL(res.url()).pathname.endsWith('/fund-review/review'));
 await dialog.getByRole('button',{name:'Approve reviewed brief',exact:true}).click();expect((await approval).ok()).toBe(true);
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Download reviewed brief',exact:true}).click();
 const brief=await download;await brief.saveAs(info.outputPath('reviewed-public-reference-brief.html'));
 await expect(page.getByText('Loading review findings…',{exact:true})).not.toBeVisible();
 await page.screenshot({path:info.outputPath('independently-reviewed-scope.png'),fullPage:true});
 expect((await result()).summary.financially_verified).toBe(false);
});
