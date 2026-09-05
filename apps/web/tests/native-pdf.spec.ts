import type { Page } from '@playwright/test';
import { test,expect,attachLocalSurfaces } from './fixtures';
import { readFileSync,writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
function setting(name:string){const value=process.env[name];if(!value)throw new Error(name+' is required for the real PDF evidence browser check.');return value;}
const packId=()=>process.env.CLOSEGRAPH_TEST_PDF_PACK_ID??'synthetic-pdf-pack';
async function openPack(page:Page,role:'PREPARER'|'REVIEWER'){
 await page.goto(process.env.CLOSEGRAPH_UI_URL??'http://127.0.0.1:24173');
 await page.getByRole('textbox',{name:'Username',exact:true}).fill(setting('CLOSEGRAPH_TEST_'+role+'_USERNAME'));
 await page.getByLabel('Password',{exact:true}).fill(setting('CLOSEGRAPH_TEST_'+role+'_PASSWORD'));
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByRole('combobox',{name:'Reporting pack'})).toBeVisible();
 if(await page.getByRole('combobox',{name:'Reporting pack'}).inputValue()!==packId()){
  const response=page.waitForResponse(r=>r.request().method()==='GET'&&r.url().endsWith('/api/packs/'+packId()));
  await page.getByRole('combobox',{name:'Reporting pack'}).selectOption(packId());expect((await response).ok()).toBe(true);
 }
 await expect(page.getByRole('combobox',{name:'Reporting pack'})).toHaveValue(packId());
}
async function settled(page:Page){
 await expect.poll(()=>page.evaluate(async id=>(await(await fetch('/api/packs/'+id)).json()).execution_status,packId()),{timeout:45000}).not.toMatch(/PENDING|RUNNING|QUEUED/);
 await page.getByRole('button',{name:'Refresh current version'}).click();
 await expect(page.getByText('Checking this pack version',{exact:true})).toHaveCount(0);
}
test('real PDF provider mode retains honest state and original citation',async({browser})=>{
 test.setTimeout(150000);
 const mode=setting('CLOSEGRAPH_TEST_PDF_MODE');expect(['DISABLED','CAPTURED_REPLAY']).toContain(mode);
 const context=await browser.newContext();await attachLocalSurfaces(context);const page=await context.newPage();await openPack(page,'PREPARER');
 {
  await page.getByRole('button',{name:'Upload source',exact:true}).click();
  await page.getByRole('combobox',{name:'Source purpose'}).selectOption('reporting-evidence');
  await page.getByLabel('Source file',{exact:true}).setInputFiles(setting('CLOSEGRAPH_TEST_PDF_FILE'));
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/uploads'));
  await page.getByRole('button',{name:'Upload and check source'}).click();expect((await response).ok()).toBe(true);
  await expect(page.getByRole('dialog')).toHaveCount(0);
 }
 await settled(page);
 const pack=await page.evaluate(async id=>(await(await fetch('/api/packs/'+id)).json()),packId());
 writeFileSync('test-results/pdf-'+mode.toLowerCase()+'-snapshot.json',JSON.stringify(pack,null,2));
 if(mode==='DISABLED'){
  expect(JSON.stringify(pack)).toMatch(/DISABLED/i);
  expect(pack.checks.some((check:{required:boolean;status:string})=>check.required&&!['PASS','NOT_APPLICABLE'].includes(check.status))).toBe(true);
  await page.getByRole('link',{name:'Checks',exact:true}).click();
  await page.getByRole('button',{name:'Processing and review details'}).click();
  await page.screenshot({path:'test-results/pdf-disabled-source.png',fullPage:true});
  const reviewerContext=await browser.newContext();await attachLocalSurfaces(reviewerContext);const reviewer=await reviewerContext.newPage();await openPack(reviewer,'REVIEWER');
  await reviewer.getByRole('link',{name:'Approval',exact:true}).click();
  await expect(reviewer.getByRole('button',{name:/^Approve version/})).toBeDisabled();
  await expect(reviewer.getByRole('button',{name:'Publish reviewed pack'})).toBeDisabled();
  await reviewerContext.close();
 }else{
  const observations=pack.extraction_observations.filter((observation:{mode?:string})=>observation.mode==='REPLAY');
  expect(observations.length).toBeGreaterThan(0);
  const evidence=Object.values(pack.evidence) as {source_id:string;content_hash:string;document_version_id:string;response_content_hash?:string;locator?:{original_page?:number}}[];
  const citations=evidence.filter(source=>source.source_id==='reporting-evidence'&&source.locator?.original_page);
  expect(citations.length).toBeGreaterThan(0);
  const originalHash=createHash('sha256').update(readFileSync(setting('CLOSEGRAPH_TEST_PDF_FILE'))).digest('hex');
  for(const source of citations){
   expect(source.content_hash).toBe(originalHash);
   expect(observations.some((observation:{response_content_hash?:string})=>observation.response_content_hash===source.response_content_hash)).toBe(true);
  }
  await page.getByRole('link',{name:'Correction',exact:true}).click();
  await page.getByRole('tab',{name:'Reporting evidence',exact:true}).click();
  await expect(page.locator('.pdf-highlight')).toBeVisible();
  await expect(page.locator('.pdf-evidence figcaption')).toHaveText('Original PDF · page '+citations[0].locator!.original_page);
  await page.getByText('Read original page text',{exact:true}).click();
  await expect(page.locator('.pdf-evidence details').getByText(setting('CLOSEGRAPH_TEST_PDF_TEXT'),{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Source and extraction details'}).click();
  await expect(page.getByText('REPLAY',{exact:false}).first()).toBeVisible();
  await page.screenshot({path:'test-results/pdf-captured-replay-citation.png',fullPage:true});
 }
 await context.close();
});
