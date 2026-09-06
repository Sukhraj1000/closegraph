import {test,expect} from './fixtures';
test.use({trace:'off'});
test('four business accounts preserve their actual access',async({page},info)=>{
 const roles=[['Accountant','accountant','PREPARER'],['Account manager','account_manager','REVIEWER'],['Fund manager','fund_manager','FUND_MANAGER'],['Investor','investor','INVESTOR']];
 for(const [label,username,key] of roles){
  await page.goto('/');await expect(page.getByRole('heading',{name:'Sign in to CloseGraph'})).toBeVisible();
  if(key==='PREPARER')await page.screenshot({path:info.outputPath('business-account-login.png')});
  await page.getByRole('button',{name:label,exact:true}).click();await expect(page.getByLabel('Username',{exact:true})).toHaveValue(username);
  await page.getByLabel('Password',{exact:true}).fill(process.env['CLOSEGRAPH_TEST_'+key+'_PASSWORD']!);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.locator('.fr-identity')).toHaveText(label);
  const nav=page.getByRole('navigation',{name:'Main navigation'});
  if(['INVESTOR','FUND_MANAGER'].includes(key)){await expect(nav.getByRole('button',{name:'New review',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:'Requests',exact:true}).first()).toBeVisible();}
  await page.screenshot({path:info.outputPath(username+'-workspace.png'),fullPage:true});
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
 }
});
