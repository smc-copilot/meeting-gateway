from fastapi import APIRouter
from app.api.business import router as business
from app.api.portal import router as portal
from app.api.admin.router import router as admin
router=APIRouter()
router.include_router(business)
router.include_router(portal)
router.include_router(admin)
