import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app_state import state
from db import apply_to_state
from routes.api import router as api_router, _start_reader
from routes.pages import router as pages_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("SHH Reader starting up")
    auto = apply_to_state(state)
    if auto and state.device_type and state.connection_mode:
        log.info("Auto-starting reader from saved settings")
        await _start_reader()
    yield
    from routes.api import _stop_tasks
    await _stop_tasks()
    log.info("SHH Reader shut down")


app = FastAPI(title="SHH Reader", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(api_router)
app.include_router(pages_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)