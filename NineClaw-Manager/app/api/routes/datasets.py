"""RAGFlow-compatible dataset routes.



Maps RAGFlow ``dataset`` to local knowledge base (``kb_id``).

"""



from __future__ import annotations



from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.parse_documents_handler import parse_documents_json_response
from app.db.session import get_session
from app.schemas.dataset import ParseDocumentsRequest

from app.services.knowledge_factory import KnowledgeBackend, _get_knowledge_service



router = APIRouter(

    prefix="/datasets",

    tags=["datasets"],

)





async def get_knowledge_service_dep(session: AsyncSession = Depends(get_session)) -> KnowledgeBackend:
    return await _get_knowledge_service(session)




@router.post(

    "/{dataset_id}/chunks",

    summary="解析文档（RAGFlow 兼容）",

    response_model=None,

)

async def parse_documents(

    dataset_id: str,

    body: ParseDocumentsRequest = Body(...),

    service: KnowledgeBackend = Depends(get_knowledge_service_dep),

):

    """

    解析指定数据集中的文档，参照 RAGFlow ``POST /api/v1/datasets/{dataset_id}/chunks``。



    请求体::



        {"document_ids": ["97a5f1c2759811efaa500242ac120004"]}



    成功响应::



        {"code": 0}

    """

    return parse_documents_json_response(service, dataset_id, body.document_ids)


