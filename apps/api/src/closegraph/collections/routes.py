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
    @router.get('/{identity}')
    def get(identity:str,actor=Depends(user)):return call('get',identity,actor)
    @router.get('/{identity}/history')
    def history(identity:str,actor=Depends(user)):return call('history',identity,actor)
    @router.post('/{identity}/sources')
    def upload(identity:str,command:Upload,actor=Depends(user)):return call('upload',identity,actor,command.expected_version,command.filename,command.media_type,command.content_base64)
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
    return router
