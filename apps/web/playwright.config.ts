import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
 testDir:'./tests',
 fullyParallel:false,
 workers:1,
 timeout:60000,
 expect:{timeout:10000},
 reporter:[['list'],['json',{outputFile:process.env.CLOSEGRAPH_TEST_REPORT??'test-results/browser-results.json'}]],
 use:{...devices['Desktop Chrome'],baseURL:process.env.CLOSEGRAPH_UI_URL??'http://127.0.0.1:24173',connectOptions:process.env.CLOSEGRAPH_BROWSER_WS_ENDPOINT?{wsEndpoint:process.env.CLOSEGRAPH_BROWSER_WS_ENDPOINT}:undefined,trace:'retain-on-failure',screenshot:'only-on-failure'},
 projects:[{name:'stories',testMatch:'stories.spec.ts'},{name:'native',testMatch:'native-journey.spec.ts'},{name:'pdf',testMatch:'native-pdf.spec.ts'},{name:'collections',testMatch:'collections.spec.ts'}],
});
