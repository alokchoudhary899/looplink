from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routes_internal import router as internal_router
from app.routes_public import router as public_router

app = FastAPI(title="LoopLink")

# Tables are created at startup for this single-process sandbox exercise —
# no migration framework needed (see TECH_NOTES.md "what we cut").
Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(internal_router)
app.include_router(public_router)


@app.get("/")
def root():
    return RedirectResponse(url="/campaigns")
