"""Explicit human edits preserve original values and source membership."""
from copy import deepcopy
import json
from uuid import uuid4


def _lineage(table, row, column):
    existing = row.get('lineage', {})
    if column in existing:
        return deepcopy(existing[column])
    return [{'table_id':table['table_id'],'row_id':row['row_id'],'column_key':column,
             'source_id':table['source_id'],'locator':deepcopy(row.get('locators',{}).get(column))}]


def _combined_lineage(table, originals, column):
    result, seen = [], set()
    for row in originals:
        for reference in _lineage(table, row, column):
            key=json.dumps(reference,sort_keys=True,separators=(',',':'))
            if key not in seen:result.append(reference);seen.add(key)
    return result


def apply_edits(table, edits, issues, reason, actor, *, related_tables=None):
    if not isinstance(edits,list) or not 1<=len(edits)<=200:raise ValueError('Provide 1..200 edits')
    columns={c['key'] for c in table['columns']};applied=[]
    def row(identity):
        result=next((r for r in table['rows'] if r['row_id']==identity),None)
        if result is None:raise ValueError('Unknown row')
        return result
    def key(edit):
        value=edit.get('column_key')
        if not isinstance(value,str) or value not in columns:raise ValueError('Unknown column')
        return value
    def text(value):
        if value is not None and (not isinstance(value,str) or len(value)>100000):raise ValueError('Cell values must be bounded strings or null')
        return value
    def add_issue(code,message,**fields):
        issues.append({'id':'issue-'+uuid4().hex,'severity':'error','code':code,'message':message,'table_id':table['table_id'],'source_id':table['source_id'],'stage':'extraction',**fields})
    for edit in edits:
        if not isinstance(edit,dict):raise ValueError('Each edit must be an object')
        op=edit.get('op');detail=deepcopy(edit)
        if op=='set_cell':
            target=row(edit.get('row_id'));column=key(edit);target.setdefault('raw_values',deepcopy(target['values']))
            operation=target.get('human_operation',{});inherited_count=operation.get('inherited_correction_count')
            if operation.get('op')=='split_row' and (type(inherited_count) is not int or not 0<=inherited_count<=len(target.get('corrections',[]))):
                operation['inherited_correction_count']=len(target.get('corrections',[]))
            detail['previous']=target['values'].get(column);target['values'][column]=text(edit.get('value'))
            target.setdefault('corrections',[]).append({'column_key':column,'previous':detail['previous'],'value':edit.get('value'),'actor_id':actor,'reason':reason})
        elif op=='rename_column':
            column=key(edit);label=text(edit.get('label'))
            if not label or not label.strip():raise ValueError('Column label cannot be empty')
            for c in table['columns']:
                if c['key']==column:detail['previous']=c['label'];c['label']=label
        elif op=='exclude_row':
            target=row(edit.get('row_id'));target['excluded']=True;target['exclusion_reason']=edit.get('reason') or reason
        elif op=='set_header':
            target=row(edit.get('row_id'))
            for c in table['columns']:c['label']=str(target['values'].get(c['key']) or c['key'])
            target['excluded']=True;target['exclusion_reason']='Selected as header: '+reason
            table.setdefault('metadata',{})['header_row_id']=target['row_id']
        elif op=='split_row':
            target=row(edit.get('row_id'));values=edit.get('values')
            if not isinstance(values,list) or not 2<=len(values)<=20:raise ValueError('Split needs 2..20 explicit row values')
            new=[]
            for value in values:
                if not isinstance(value,dict) or set(value)-columns:raise ValueError('Split uses unknown columns')
                created=deepcopy(target);created['row_id']=target['row_id']+'-split-'+uuid4().hex[:12]
                created['raw_values']=deepcopy(target.get('raw_values',target['values']));created['values']={k:text(value.get(k)) for k in columns}
                created['lineage']={column:_lineage(table,target,column) for column in columns}
                created['source_row_ids']=[target['row_id']]
                created['human_operation']={'op':op,'actor_id':actor,'reason':reason,
                                            'inherited_correction_count':len(created.get('corrections',[]))}
                new.append(created)
            position=table['rows'].index(target);table['rows'][position:position+1]=new;detail['new_row_ids']=[r['row_id'] for r in new]
        elif op=='merge_rows':
            identities=edit.get('row_ids')
            if not isinstance(identities,list) or not 2<=len(identities)<=20 or any(not isinstance(i,str) for i in identities) or len(set(identities))!=len(identities):raise ValueError('Merge needs 2..20 distinct rows')
            originals=[row(i) for i in identities];target=deepcopy(originals[0]);target['row_id']='merge-'+uuid4().hex
            target['source_rows']=deepcopy(originals);target['source_row_ids']=identities;target['human_operation']={'op':op,'actor_id':actor,'reason':reason}
            target['values']={};target['raw_values']={};target['source_locations']={};target['locators']={};target['lineage']={}
            for column in columns:target['lineage'][column]=_combined_lineage(table,originals,column)
            for c in columns:
                nonempty=list(dict.fromkeys(r['values'].get(c) for r in originals if r['values'].get(c) not in (None,'')))
                target['values'][c]=nonempty[0] if len(nonempty)==1 else None
                target['source_locations'][c]=[location for r in originals for location in ([r.get('locators',{}).get(c)] + r.get('source_locations',{}).get(c,[])) if location]
                if len(nonempty)==1:
                    chosen=next((r.get('locators',{}).get(c) for r in originals if r['values'].get(c)==nonempty[0] and r.get('locators',{}).get(c)),None)
                    if chosen:target['locators'][c]=deepcopy(chosen)
                if len(nonempty)>1:add_issue('merge_conflict','Merged rows contain different values; correct the cell and resolve this issue',row_id=target['row_id'],column_key=c,details={'values':nonempty})
            position=min(table['rows'].index(r) for r in originals);table['rows']=[r for r in table['rows'] if r['row_id'] not in identities];table['rows'].insert(position,target);detail['new_row_id']=target['row_id']
        elif op=='set_pdf_citation':
            from .repair import set_pdf_citation
            detail['affected_cells']=set_pdf_citation(table,edit,actor=actor,reason=reason)
        elif op=='mark_unresolved':
            message=text(edit.get('message'))
            if not message:raise ValueError('Describe the unresolved extraction problem')
            add_issue('human_unresolved',message)
        elif op=='resolve_issue':
            selected=next((i for i in issues if i['id']==edit.get('issue_id') and i.get('table_id')==table['table_id']),None)
            if not selected or selected.get('code') not in ('human_unresolved','merge_conflict'):raise ValueError('This issue requires an actual extraction or validation repair')
            if selected['code']=='merge_conflict' and row(selected['row_id'])['values'].get(selected['column_key']) is None:raise ValueError('Correct the conflicting cell before resolving it')
            selected.update(resolved=True,resolution={'actor_id':actor,'reason':edit.get('reason') or reason})
        else:raise ValueError('Unsupported edit operation')
        applied.append(detail)
    from .repair import repair_parser_issues
    repaired=repair_parser_issues(table,issues,actor=actor,reason=reason,related_tables=related_tables)
    if repaired:applied.append({'op':'parser_issues_repaired','issue_ids':repaired})
    return applied
