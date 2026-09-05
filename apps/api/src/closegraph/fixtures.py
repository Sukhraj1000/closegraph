"""Fictional labelled local-only acceptance data. No customer data."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import json
from openpyxl import Workbook

SCOPE={'tenant_id':'synthetic-tenant','fund_id':'synthetic-fund','pack_id':'synthetic-pack'}
CONTEXT={'entity_id':'0012','period':'2026-Q1','currency':'GBP'}
RULE={**CONTEXT,'approved':True,'version':'fictional-fee-v1','approval_id':'synthetic-approved-fee-rule','tolerance':'0.01','tolerance_version':'penny-v1'}
COLUMNS=('entity_id','period','currency','metric','value','scale')
CAPITAL=b'entity_id,period,currency,metric,value,scale\n0012,2026-Q1,GBP,capital,12000000,units\n'
FEE_RULE=b'entity_id,period,currency,metric,value,scale\n0012,2026-Q1,GBP,fee_rate,0.005,units\n'
BINDINGS=[['fee','Pack','B6'],['statement_fee','Pack','B7'],['total','Pack','B8']]


def workbook_bytes(value=75000):
    workbook=Workbook(); sheet=workbook.active; sheet.title='Pack'
    sheet.append(['SYNTHETIC — fictional acceptance fixture'])
    for row in [('Entity','0012'),('Period','2026-Q1'),('Currency','GBP'),('Metric','Value'),('Fee',value),('Statement fee',value),('Total fee',value)]: sheet.append(row)
    sheet.column_dimensions['A'].width=48; sheet.column_dimensions['B'].width=20
    for address in ['B6','B7','B8']: sheet[address].number_format='#,##0.00'
    workbook.properties.created=workbook.properties.modified=datetime(2026,1,1)
    out=BytesIO(); workbook.save(out); return out.getvalue()


def fixture_bytes():
    return {'capital.csv':CAPITAL,'fee-rule.csv':FEE_RULE,'original.xlsx':workbook_bytes(),'expected.xlsx':workbook_bytes(60000)}


def build_fixture(destination):
    destination=Path(destination); destination.mkdir(parents=True,exist_ok=True)
    for name,data in fixture_bytes().items(): (destination/name).write_bytes(data)
    (destination/'README.md').write_text('# Synthetic CloseGraph fixture\n\nFictional fund 0012, GBP, 2026-Q1. Not client data. Fee is capital 12,000,000 × 0.005 = 60,000. Original fee and statement fee are both 75,000. Correcting only the fee must leave source-to-pack reconciliation failed.\n')
    (destination/'expected.json').write_text(json.dumps({'label':'SYNTHETIC',**SCOPE,'context':CONTEXT,'rule':RULE,'expected':{'fee':'60000','statement_fee':'60000','total':'60000'},'bindings':BINDINGS},indent=2))
    return {name:destination/name for name in fixture_bytes()}
