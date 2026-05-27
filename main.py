from contextlib import asynccontextmanager

import click
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from database import run_migrations
from routers import auth, files



@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(title="Simulizer Auth API", lifespan=lifespan)

app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:6001", "http://localhost:8001", "https://simulizer.net", "https://www.simulizer.net", "https://auth.simulizer.net"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(files.router)


@app.head("/health")
def health():
    return {"status": "ok"}

@click.command()
@click.option('-p', '--port', default=6001, type=int, help='Port to run the server on')
def main(port: int):
    import uvicorn
    uvicorn.run("main:app", reload=True, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")

if __name__ == "__main__":
    main()
