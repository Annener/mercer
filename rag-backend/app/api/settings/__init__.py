from fastapi import APIRouter

from .status import router as status_router
from .params import router as params_router
from .domains import router as domains_router
from .gen_models import router as gen_models_router
from .emb_models import router as emb_models_router
from .vaults import router as vaults_router
from .pipelines import router as pipelines_router

router = APIRouter()

router.include_router(status_router)
router.include_router(params_router)
router.include_router(domains_router)
router.include_router(gen_models_router)
router.include_router(emb_models_router)
router.include_router(vaults_router)
router.include_router(pipelines_router)
