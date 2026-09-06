export const roleAccounts=[{username:'accountant',label:'Accountant'},{username:'account_manager',label:'Account manager'},{username:'fund_manager',label:'Fund manager'},{username:'investor',label:'Investor'}];
export function roleLabel(role:string){return ({PREPARER:'Accountant',ACCOUNTANT:'Accountant',REVIEWER:'Account manager',ACCOUNT_MANAGER:'Account manager',FUND_MANAGER:'Fund manager',INVESTOR:'Investor'} as Record<string,string>)[role.toUpperCase()]??'Team member';}
export function accountLabel(username:string,role:string){const label=roleLabel(role);return ['preparer','reviewer',...roleAccounts.map(a=>a.username)].includes(username)?label:username+' · '+label;}

export function actorLabel(username:string){return ({preparer:"Accountant",accountant:"Accountant",reviewer:"Account manager",account_manager:"Account manager",fund_manager:"Fund manager",investor:"Investor"} as Record<string,string>)[username]??username;}
