"""Collection routes reuse the local session, Origin and CSRF boundaries."""
from typing import Annotated, Any, Literal
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response
from closegraph.api.app import COOKIE_NAME
from closegraph.api.ports import DomainUnavailable

class Command(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
class Version(Command):
    expected_version: int=Field(ge=1)
class Create(Command):
    title: str=Field(min_length=1,max_length=200)
    fund_id: str=Field(min_length=1,max_length=256)
class Upload(Version):
    filename: str=Field(min_length=1,max_length=256,pattern=r'^[^/\\\x00-\x1f]+$')
    media_type: str=Field(max_length=256)
    content_base64: str=Field(min_length=1,max_length=44739244)
    document_id: str|None=None
    parent_revision_id: str|None=None
    reason: str=Field(default='Initial upload',min_length=1,max_length=2000)
    period: str|None=Field(default=None,max_length=100)
    idempotency_key: str|None=Field(default=None,min_length=1,max_length=200)
    task_id: str|None=None
    side: Literal['statement','journal']|None=None
    defer_processing: bool=False
    as_of: str|None=Field(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$')
class Edit(Version):
    dataset_id: str
    edits: list[dict[str,Any]]=Field(min_length=1,max_length=200)
    reason: str=Field(min_length=1,max_length=2000)
class Accept(Version):
    dataset_id: str|None=None
class Process(Version):
    stage: Literal['extract']|None=None
    source_id: str|None=None
class Recipe(Version):
    recipe: dict[str,Any]
class Review(Version):
    decision: Literal['APPROVE','REJECT']
    reason: str=Field(min_length=1,max_length=2000)
class Export(Version):
    dataset_id: str
    format: Literal['csv','xlsx']
    template_source_id: str|None=None
    bindings: dict[str,Any]|None=None


class Membership(Command):
    actor_id: str
    party: Literal['accountant','account_manager','fund_manager','investor']
    document_ids: list[str]=Field(default_factory=list,max_length=500)
    request_ids: list[str]=Field(default_factory=list,max_length=500)
class Members(Version):
    members: list[Membership]=Field(max_length=200)
class Requirements(Version):
    requirements: list[dict[str,Any]]=Field(max_length=100)
class Coverage(Version):
    reason: str=Field(min_length=1,max_length=2000)
class DocumentConfig(Version):
    business_keys: dict[str,Any]
class Flag(Version):
    title: str=Field(min_length=1,max_length=200)
    reason: str=Field(min_length=1,max_length=2000)
    owner_actor_id: str
    document_id: str|None=None
    blocking: bool=False
    idempotency_key: str|None=Field(default=None,min_length=1,max_length=200)
class TaskAction(Version):
    action: Literal['acknowledge','evidence_received','request_verification','resolve','release','reopen','make_blocking']
    reason: str=Field(default='',max_length=2000)
    source_id: str|None=None
    idempotency_key: str|None=Field(default=None,min_length=1,max_length=200)


class Reconcile(Version):
    source_sides: dict[str,Literal['statement','journal']]
    config: dict[str,Any]=Field(default_factory=dict)
    reason: str=Field(default='Compare uploaded evidence',min_length=1,max_length=2000)
    idempotency_key: str|None=Field(default=None,max_length=200)
class ReconcileAssignment(Version):
    item_ids: list[str]=Field(min_length=1,max_length=1000)
    owner_actor_id: str
    reason: str=Field(min_length=1,max_length=2000)
    due_at: str|None=None
class FundReview(Version):
    config: dict[str,Any]=Field(default_factory=dict)
    reason: str=Field(default='Review uploaded reporting evidence',min_length=1,max_length=2000)
    idempotency_key: str|None=Field(default=None,min_length=1,max_length=200)
class NotificationRead(Command):
    notification_ids: list[str]=Field(max_length=1000)

def collection_router(auth,services):
    router=APIRouter(prefix='/api/collections')
    def user(request:Request):
        principal=auth.resolve(request.cookies.get(COOKIE_NAME))
        if principal is None:raise HTTPException(401,'authentication required')
        if request.method not in ('GET','HEAD') and not auth.check_csrf(principal,request.headers.get('x-csrf-token')):raise HTTPException(403,'invalid CSRF token')
        return principal.actor.actor_id
    def call(name,*args,**kwargs):
        if services is None:raise DomainUnavailable()
        try:return getattr(services,name)(*args,**kwargs)
        except ValueError as exc:raise HTTPException(422,str(exc)[:1000]) from exc
    @router.get('')
    def listing(actor=Depends(user)):return call('list',actor)
    @router.post('',status_code=201)
    def create(command:Create,actor=Depends(user)):return call('create',actor,command.title.strip(),command.fund_id)
    @router.get('/notifications')
    def inbox(actor=Depends(user)):return call('inbox',actor)
    @router.get('/{identity}')
    def get(identity:str,actor=Depends(user)):return call('get',identity,actor)
    @router.get('/{identity}/history')
    def history(identity:str,actor=Depends(user)):return call('history',identity,actor)
    @router.post('/{identity}/sources')
    def upload(identity:str,command:Upload,actor=Depends(user)):return call('upload',identity,actor,command.expected_version,command.filename,command.media_type,command.content_base64,document_id=command.document_id,parent_revision_id=command.parent_revision_id,reason=command.reason,period=command.period,idempotency_key=command.idempotency_key,task_id=command.task_id,as_of=command.as_of,side=command.side,defer_processing=command.defer_processing)
    @router.post('/{identity}/process')
    def process(identity:str,command:Process,actor=Depends(user)):return call('process',identity,actor,command.expected_version,command.stage,command.source_id)
    @router.get('/{identity}/datasets/{dataset_id}/rows')
    def rows(identity:str,dataset_id:str,offset:Annotated[int,Query(ge=0)]=0,limit:Annotated[int,Query(ge=1,le=500)]=100,row_id:str|None=None,actor=Depends(user)):return call('rows',identity,actor,dataset_id,offset,limit,row_id)
    @router.post('/{identity}/edits')
    def edits(identity:str,command:Edit,actor=Depends(user)):return call('edit',identity,actor,command.expected_version,command.dataset_id,command.edits,command.reason)
    @router.post('/{identity}/accept')
    def accept(identity:str,command:Accept,actor=Depends(user)):return call('accept',identity,actor,command.expected_version,command.dataset_id)
    @router.put('/{identity}/recipe')
    def recipe(identity:str,command:Recipe,actor=Depends(user)):return call('recipe',identity,actor,command.expected_version,command.recipe)
    @router.post('/{identity}/review')
    def review(identity:str,command:Review,actor=Depends(user)):return call('review',identity,actor,command.expected_version,command.decision,command.reason)
    @router.post('/{identity}/exports')
    def export(identity:str,command:Export,actor=Depends(user)):return call('export',identity,actor,command.expected_version,command.dataset_id,command.format,command.template_source_id,command.bindings)
    def download(identity,actor,resource_id,artifact=False,candidate=False):
        content,media_type,filename=call('download',identity,actor,resource_id,artifact=artifact,candidate=candidate)
        return Response(content,media_type=media_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})
    @router.get('/{identity}/sources/{source_id}/download')
    def source(identity:str,source_id:str,actor=Depends(user)):return download(identity,actor,source_id)
    @router.get('/{identity}/artifacts/{artifact_id}')
    def artifact(identity:str,artifact_id:str,actor=Depends(user)):return download(identity,actor,artifact_id,True)
    @router.get('/{identity}/candidates/{candidate_id}')
    def candidate(identity:str,candidate_id:str,actor=Depends(user)):return download(identity,actor,candidate_id,candidate=True)
    @router.get('/{identity}/participants')
    def participants(identity:str,actor=Depends(user)):return call('participants',identity,actor)
    @router.put('/{identity}/members')
    def members(identity:str,command:Members,actor=Depends(user)):return call('members',identity,actor,command.expected_version,[m.model_dump() for m in command.members])
    @router.put('/{identity}/requirements')
    def requirements(identity:str,command:Requirements,actor=Depends(user)):return call('requirements',identity,actor,command.expected_version,command.requirements)
    @router.post('/{identity}/evaluate')
    def evaluate(identity:str,command:Version,actor=Depends(user)):return call('evaluate',identity,actor,command.expected_version)
    @router.post('/{identity}/sources/{source_id}/verify-coverage')
    def coverage(identity:str,source_id:str,command:Coverage,actor=Depends(user)):return call('verify_coverage',identity,actor,command.expected_version,source_id,command.reason)
    @router.put('/{identity}/documents/{document_id}')
    def document(identity:str,document_id:str,command:DocumentConfig,actor=Depends(user)):return call('configure_document',identity,actor,command.expected_version,document_id,command.business_keys)
    @router.get('/{identity}/comparisons/{comparison_id}')
    def comparison(identity:str,comparison_id:str,offset:Annotated[int,Query(ge=0)]=0,limit:Annotated[int,Query(ge=1,le=500)]=100,actor=Depends(user)):return call('comparison',identity,actor,comparison_id,offset,limit)
    @router.post('/{identity}/flags')
    def flag(identity:str,command:Flag,actor=Depends(user)):return call('flag',identity,actor,command.expected_version,command.title,command.reason,command.owner_actor_id,document_id=command.document_id,blocking=command.blocking,idempotency_key=command.idempotency_key)
    @router.post('/{identity}/tasks/{task_id}/actions')
    def task_action(identity:str,task_id:str,command:TaskAction,actor=Depends(user)):return call('task_action',identity,actor,command.expected_version,task_id,command.action,command.reason,source_id=command.source_id,idempotency_key=command.idempotency_key)
    @router.post('/{identity}/comparisons/{comparison_id}/review')
    def review_comparison(identity:str,comparison_id:str,command:Coverage,actor=Depends(user)):return call('review_comparison',identity,actor,command.expected_version,comparison_id,command.reason)
    @router.post('/{identity}/reconciliation')
    def reconcile(identity:str,command:Reconcile,actor=Depends(user)):return call('reconcile',identity,actor,command.expected_version,command.source_sides,command.config,command.reason,command.idempotency_key)
    @router.get('/{identity}/reconciliation/results')
    def reconciliation_results(identity:str,status:Literal['matched','difference','missing','needs_input']|None=None,q:str=Query(default='',max_length=500),offset:int=Query(default=0,ge=0),limit:int=Query(default=50,ge=1,le=500),actor=Depends(user)):return call('reconciliation_results',identity,actor,status,q,offset,limit)
    @router.get('/{identity}/reconciliation/download')
    def reconciliation_download(identity:str,reviewed:bool=False,actor=Depends(user)):
        content,media_type,filename=call('reconciliation_download',identity,actor,reviewed)
        return Response(content,media_type=media_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})
    @router.post('/{identity}/reconciliation/review')
    def reconciliation_review(identity:str,command:Review,actor=Depends(user)):return call('reconciliation_review',identity,actor,command.expected_version,command.decision,command.reason)
    @router.post('/{identity}/reconciliation/assign')
    def reconciliation_assign(identity:str,command:ReconcileAssignment,actor=Depends(user)):return call('reconciliation_assign',identity,actor,command.expected_version,command.item_ids,command.owner_actor_id,command.reason,command.due_at)
    @router.post('/{identity}/notifications/read')
    def notifications_read(identity:str,command:NotificationRead,actor=Depends(user)):return call('notifications_read',identity,actor,command.notification_ids)
    @router.post('/{identity}/fund-review')
    def fund_review(identity:str,command:FundReview,actor=Depends(user)):
        return call('fund_review_start',identity,actor,command.expected_version,command.config,command.reason,command.idempotency_key)
    @router.get('/{identity}/fund-review/results')
    def fund_review_results(identity:str,status:Literal['difference','needs_input','passed']|None=None,q:str=Query(default='',max_length=500),offset:int=Query(default=0,ge=0),limit:int=Query(default=50,ge=1,le=500),blocking:bool|None=None,actor=Depends(user)):
        return call('fund_review_results',identity,actor,status,q,offset,limit,blocking)
    @router.get('/{identity}/fund-review/findings/{finding_id}/records')
    def fund_review_records(identity:str,finding_id:str,offset:int=Query(default=0,ge=0),limit:int=Query(default=50,ge=1,le=500),actor=Depends(user)):
        return call('fund_review_records',identity,actor,finding_id,offset,limit)
    @router.get('/{identity}/fund-review/findings/{finding_id}/download')
    def fund_review_records_download(identity:str,finding_id:str,actor=Depends(user)):
        content,media_type,filename=call('fund_review_records_download',identity,actor,finding_id)
        return Response(content,media_type=media_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})
    @router.post('/{identity}/fund-review/assign')
    def fund_review_assign(identity:str,command:ReconcileAssignment,actor=Depends(user)):
        return call('fund_review_assign',identity,actor,command.expected_version,command.item_ids,command.owner_actor_id,command.reason,command.due_at)
    @router.post('/{identity}/fund-review/review')
    def fund_review_review(identity:str,command:Review,actor=Depends(user)):
        return call('fund_review_review',identity,actor,command.expected_version,command.decision,command.reason)
    @router.get('/{identity}/fund-review/download')
    def fund_review_download(identity:str,reviewed:bool=False,actor=Depends(user)):
        content,media_type,filename=call('fund_review_download',identity,actor,reviewed)
        return Response(content,media_type=media_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})
    return router
