import type { Page } from '@playwright/test';
import { test, expect, attachLocalSurfaces } from './fixtures';
import path from 'node:path';
import { readFileSync,writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
function setting(name:string){const value=process.env[name];if(!value)throw new Error(name+' is required for the real local API browser journey.');return value;}
async function login(page:Page,role:'PREPARER'|'REVIEWER'){
 await page.goto((process.env.CLOSEGRAPH_UI_URL??'http://127.0.0.1:24173')+'/#reports');
 await page.getByRole('textbox',{name:'Username',exact:true}).fill(setting('CLOSEGRAPH_TEST_'+role+'_USERNAME'));
 await page.getByLabel('Password',{exact:true}).fill(setting('CLOSEGRAPH_TEST_'+role+'_PASSWORD'));
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByRole('link',{name:'Overview',exact:true})).toBeVisible();
 const packPicker=page.getByRole('combobox',{name:'Reporting pack'});
 if(await packPicker.inputValue()!==setting('CLOSEGRAPH_TEST_PACK_ID')){
  const detail=page.waitForResponse(r=>r.request().method()==='GET'&&r.url().endsWith('/api/packs/'+setting('CLOSEGRAPH_TEST_PACK_ID')));
  await packPicker.selectOption(setting('CLOSEGRAPH_TEST_PACK_ID'));expect((await detail).ok()).toBe(true);
 }
 await expect(packPicker).toHaveValue(setting('CLOSEGRAPH_TEST_PACK_ID'));
}
async function settled(page:Page){
 await expect.poll(async()=>{return page.evaluate(async id=>{const response=await fetch('/api/packs/'+encodeURIComponent(id));const data=await response.json();return data.execution_status;},setting('CLOSEGRAPH_TEST_PACK_ID'));},{timeout:45000}).not.toMatch(/PENDING|RUNNING|QUEUED/);
 await page.getByRole('button',{name:'Refresh current version'}).click();
 await expect(page.getByText('Checking this pack version',{exact:true})).toHaveCount(0);
}
async function correct(page:Page,factId:string,source:string,reason:string){
 await page.getByRole('link',{name:'Correction',exact:true}).click();
 await page.getByRole('combobox',{name:'Pack value',exact:true}).selectOption(factId);
 const inspected=await page.evaluate(async({id,factId})=>{
  const pack=await(await fetch('/api/packs/'+id)).json(),fact=pack.facts.find((f:{fact_id:string})=>f.fact_id===factId);
  const entry=Object.entries(pack.evidence).find(([,value])=>{const source=value as {document_version_id?:string;locator?:{sheet?:string;cell?:string}};return source.document_version_id===fact.source.document_version_id&&source.locator?.sheet===fact.source.locator.sheet&&source.locator?.cell===fact.source.locator.cell;});
  if(!entry)throw new Error('Exact original source occurrence missing for '+factId);
  return {fact_id:factId,source_id:entry[0],source:entry[1]} as {fact_id:string;source_id:string;source:{document_version_id:string;content_hash:string;locator:{sheet:string;cell:string};preview_rows:{label:string;value:string}[]}};
 },{id:setting('CLOSEGRAPH_TEST_PACK_ID'),factId});
 await expect(page.getByRole('tab',{name:'Original pack',exact:true})).toHaveAttribute('aria-selected','true');
 const panel=page.getByRole('tabpanel');
 await expect(panel.getByText(inspected.source.locator.sheet+'!'+inspected.source.locator.cell,{exact:true})).toBeVisible();
 const displayedRows=await panel.locator('.paper-row').evaluateAll(rows=>rows.map(row=>({label:row.querySelector('span')?.textContent,value:row.querySelector('strong')?.textContent})));
 expect(displayedRows).toEqual(inspected.source.preview_rows);
 writeFileSync('test-results/native-'+factId+'-source-preview.json',JSON.stringify({...inspected,displayed_rows:displayedRows},null,2));
 await page.getByRole('textbox',{name:/Corrected amount/}).fill('60000.00');
 await page.getByRole('textbox',{name:'Why are you changing it?'}).fill(reason);
 const sourceKey=await page.evaluate(async({id,factId,source})=>{const pack=await(await fetch('/api/packs/'+id)).json();const match=Object.entries(pack.evidence).find(([,value])=>{const e=value as {source_id?:string;fact_ids?:string[]};return e.source_id===source&&e.fact_ids?.includes(factId);});if(!match)throw new Error('No canonical supporting evidence for '+factId);return match[0];},{id:setting('CLOSEGRAPH_TEST_PACK_ID'),factId,source});
 await page.getByRole('combobox',{name:'Supporting source'}).selectOption(sourceKey);
 const response=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().endsWith('/corrections'));
 await page.getByRole('button',{name:'Save correction',exact:true}).click();
 const correctionResponse=await response;expect(correctionResponse.status(),await correctionResponse.text()).toBe(200);
 await expect(page.getByRole('link',{name:'Checks',exact:true})).toHaveAttribute('aria-current','page');
 await settled(page);
}
test('native upload → failed repair → successful repair → independent approval → exact output download',async({browser})=>{
 test.setTimeout(180000);
 const preparerContext=await browser.newContext({acceptDownloads:true}),reviewerContext=await browser.newContext({acceptDownloads:true,viewport:{width:1280,height:900}});
 await attachLocalSurfaces(preparerContext);await attachLocalSurfaces(reviewerContext);
 const page=await preparerContext.newPage(),reviewPage=await reviewerContext.newPage();
 await login(page,'PREPARER');
 const fixtureDir=setting('CLOSEGRAPH_FIXTURE_DIR');
 for(const [source,filename] of [['capital','capital.csv'],['fee-rule','fee-rule.csv'],['original','original.xlsx']]){
  await page.getByRole('button',{name:'Upload source',exact:true}).click();
  await page.getByRole('combobox',{name:'Source purpose'}).selectOption(source);
  await page.getByLabel('Source file',{exact:true}).setInputFiles(path.join(fixtureDir,filename));
  await page.getByRole('button',{name:'Upload and check source'}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await settled(page);
 }
 await correct(page,'fee','fee-rule','Apply the source-backed authorised fee rule.');
 await expect(page.getByText('× Failed',{exact:true})).toBeVisible();
 const failedRepair=await page.evaluate(async id=>await(await fetch('/api/packs/'+id)).json(),setting('CLOSEGRAPH_TEST_PACK_ID'));
 writeFileSync('test-results/native-failed-repair.json',JSON.stringify(failedRepair,null,2));
 await page.getByRole('link',{name:'Approval',exact:true}).click();
 await expect(page.getByRole('button',{name:/^Approve version/})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Publish reviewed pack'})).toBeDisabled();
 await correct(page,'statement_fee','fee-rule','Carry the corrected fee into the dependent statement.');
 await expect(page.getByRole('button',{name:'Continue to approval'})).toBeEnabled();
 const ready=await page.evaluate(async id=>await(await fetch('/api/packs/'+id)).json(),setting('CLOSEGRAPH_TEST_PACK_ID'));
 writeFileSync('test-results/native-ready-snapshot.json',JSON.stringify(ready,null,2));
 await login(reviewPage,'REVIEWER');
 await reviewPage.getByRole('link',{name:'Checks',exact:true}).click();
 await expect(reviewPage.getByRole('region',{name:'Pack value comparison'})).toBeVisible();
 await reviewPage.getByRole('link',{name:'Approval',exact:true}).click();
 const beforeWork=await reviewPage.evaluate(async id=>await(await fetch('/api/packs/'+id+'/review-work')).json(),setting('CLOSEGRAPH_TEST_PACK_ID'));
 const beforeSample=await reviewPage.evaluate(async id=>(await (await fetch('/api/packs/'+id)).json()).version,setting('CLOSEGRAPH_TEST_PACK_ID'));
 await reviewPage.getByRole('button',{name:/^Sample /}).first().click();
 await expect(reviewPage.getByRole('link',{name:'Correction',exact:true})).toHaveAttribute('aria-current','page');
 await reviewPage.getByRole('tab',{name:'Fee rule',exact:true}).click();
 await expect.poll(async()=>reviewPage.evaluate(async id=>{const work=await(await fetch('/api/packs/'+id+'/review-work')).json();return work.counts.READY_ITEM_SAMPLED;},setting('CLOSEGRAPH_TEST_PACK_ID'))).toBe(beforeWork.counts.READY_ITEM_SAMPLED+1);
 const afterSample=await reviewPage.evaluate(async id=>(await (await fetch('/api/packs/'+id)).json()).version,setting('CLOSEGRAPH_TEST_PACK_ID'));
 expect(afterSample).toBe(beforeSample);
 await reviewPage.getByRole('button',{name:'Observed review work'}).click();
 await expect(reviewPage.getByText('Ready values sampled',{exact:true})).toBeVisible();
 await reviewPage.getByRole('link',{name:'Approval',exact:true}).click();
 // The actual candidate inspection is explicitly initiated before attestation.
 const previewDownload=reviewPage.waitForEvent('download');
 await reviewPage.getByRole('link',{name:'Inspect candidate workbook'}).click();
 const candidate=await previewDownload;expect(await candidate.failure()).toBeNull();await candidate.saveAs('test-results/candidate-preview.xlsx');
 await reviewPage.getByRole('textbox',{name:'Review note'}).fill('Inspected the candidate workbook, source evidence and all affected checks.');
 await reviewPage.getByRole('checkbox').check();
 await reviewPage.getByRole('button',{name:/^Approve version/}).click();
 await expect(reviewPage.getByRole('button',{name:'Publish reviewed pack'})).toBeEnabled();
 await reviewPage.getByRole('button',{name:'Publish reviewed pack'}).click();
 await expect(reviewPage.getByRole('link',{name:'Download reviewed workbook'})).toBeVisible();
 const downloadSnapshot=await reviewPage.evaluate(async id=>await(await fetch('/api/packs/'+id)).json(),setting('CLOSEGRAPH_TEST_PACK_ID'));
 const workbookURL=new URL(downloadSnapshot.candidate.download_url,reviewPage.url()),manifestURL=new URL(downloadSnapshot.candidate.manifest_url,reviewPage.url());
 expect(workbookURL.searchParams.get('publication_id')).toBe(downloadSnapshot.publication.publication_id);
 expect(manifestURL.searchParams.get('publication_id')).toBe(downloadSnapshot.publication.publication_id);
 await expect(reviewPage.getByRole('link',{name:'Download reviewed workbook'})).toHaveAttribute('href',downloadSnapshot.candidate.download_url);
 const workbookResponse=reviewPage.waitForResponse(response=>response.request().method()==='GET'&&response.url()===workbookURL.href);
 const workbookDownload=reviewPage.waitForEvent('download');await reviewPage.getByRole('link',{name:'Download reviewed workbook'}).click();
 const workbook=await workbookDownload;await workbook.saveAs('test-results/reviewed-pack.xlsx');expect(readFileSync('test-results/reviewed-pack.xlsx').equals(readFileSync('test-results/candidate-preview.xlsx'))).toBe(true);
 const reviewedResponse=await workbookResponse;expect(reviewedResponse.status()).toBe(200);
 const manifestResponse=reviewPage.waitForResponse(response=>response.request().method()==='GET'&&response.url()===manifestURL.href);
 const manifestDownload=reviewPage.waitForEvent('download');await reviewPage.getByRole('link',{name:'Download review manifest'}).click();
 const manifest=await manifestDownload;await manifest.saveAs('test-results/review-manifest.json');
 const reviewedManifestResponse=await manifestResponse;expect(reviewedManifestResponse.status()).toBe(200);
 const expectedWorkbookFilename=setting('CLOSEGRAPH_TEST_PACK_ID')+'-v'+downloadSnapshot.candidate.checked_version+'-current.xlsx';
 const expectedManifestFilename=setting('CLOSEGRAPH_TEST_PACK_ID')+'-v'+downloadSnapshot.candidate.checked_version+'-current-manifest.json';
 expect(workbook.suggestedFilename()).toBe(expectedWorkbookFilename);
 expect(manifest.suggestedFilename()).toBe(expectedManifestFilename);
 expect(await reviewedResponse.headerValue('content-disposition')).toBe("attachment; filename*=UTF-8''"+encodeURIComponent(expectedWorkbookFilename));
 expect(await reviewedManifestResponse.headerValue('content-disposition')).toBe("attachment; filename*=UTF-8''"+encodeURIComponent(expectedManifestFilename));
 writeFileSync('test-results/native-publication-download-verification.json',JSON.stringify({publication:downloadSnapshot.publication,checked_version:downloadSnapshot.candidate.checked_version,workbook_url:workbookURL.href,manifest_url:manifestURL.href,workbook_content_disposition:await reviewedResponse.headerValue('content-disposition'),manifest_content_disposition:await reviewedManifestResponse.headerValue('content-disposition'),workbook_filename:workbook.suggestedFilename(),manifest_filename:manifest.suggestedFilename()},null,2));
 const verification=execFileSync('python3.12',['tests/verify_download.py','test-results/reviewed-pack.xlsx','test-results/review-manifest.json',fixtureDir,setting('CLOSEGRAPH_TEST_REVIEWER_USERNAME')],{encoding:'utf8'});
 expect(verification).toContain('integrity verified');
 writeFileSync('test-results/native-download-verification.txt',verification);
 const release=await reviewPage.evaluate(async id=>await(await fetch('/api/packs/'+id)).json(),setting('CLOSEGRAPH_TEST_PACK_ID'));
 const work=await reviewPage.evaluate(async id=>await(await fetch('/api/packs/'+id+'/review-work')).json(),setting('CLOSEGRAPH_TEST_PACK_ID'));
 writeFileSync('test-results/native-released-snapshot.json',JSON.stringify(release,null,2));
 writeFileSync('test-results/native-observed-review-work.json',JSON.stringify({provenance:'AUTOMATED_LOCAL_SYNTHETIC_BROWSER_TEST',before_sample_count:beforeWork.counts.READY_ITEM_SAMPLED,before_sample_version:beforeSample,after_sample_version:afterSample,report:work},null,2));
 await expect(reviewPage.locator('.paper-row').filter({hasText:'fee_rate'}).locator('strong')).toHaveText('0.005');
 await reviewPage.evaluate(()=>window.scrollTo(0,0));
 await reviewPage.screenshot({path:'test-results/native-reviewed-pack-viewport.png',fullPage:false});
 await reviewPage.getByRole('button',{name:'Version and review history'}).click();
 await reviewPage.screenshot({path:'test-results/native-reviewed-pack.png',fullPage:true});
 await preparerContext.close();await reviewerContext.close();
});
