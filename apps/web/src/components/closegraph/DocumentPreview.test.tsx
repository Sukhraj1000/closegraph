import {render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {it,expect,vi} from 'vitest';
import {DownloadLink} from './DocumentPreview';
it('reports revoked artifact access and keeps the download available for a retry',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('Forbidden',{status:403})));
 const user=userEvent.setup();render(<DownloadLink url="/api/packs/p/artifacts/a/download" label="Inspect candidate workbook"/>);
 await user.click(screen.getByRole('link',{name:'Inspect candidate workbook'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 403');
 expect(screen.getByRole('link',{name:'Inspect candidate workbook'})).toHaveAttribute('aria-disabled','false');
 vi.unstubAllGlobals();
});
