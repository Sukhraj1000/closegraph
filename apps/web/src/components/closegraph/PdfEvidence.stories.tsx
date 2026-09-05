import type { Meta,StoryObj } from '@storybook/react-vite';
import { PdfEvidence } from './PdfEvidence';
import fixtureUrl from '../../test/fixtures/cited-original.pdf?url&no-inline';
const meta={title:'CloseGraph/Evidence/PDF original page',component:PdfEvidence,parameters:{layout:'padded'},args:{url:fixtureUrl,source:{filename:'Synthetic cited original.pdf',locator:{kind:'pdf',original_page:2,processed_page:1,coordinate_system:'points-top-left',bbox:[60,92,555,115]}}},decorators:[Story=><main style={{maxWidth:750}}><p>Synthetic original PDF fixture · no provider result</p><Story/></main>]} satisfies Meta<typeof PdfEvidence>;
export default meta;type Story=StoryObj<typeof meta>;
export const CitedOriginalPage:Story={};
