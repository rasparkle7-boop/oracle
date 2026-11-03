from __future__ import annotations

import uvicorn

from .config import settings

if __name__ == "__main__":
    uvicorn.run("oracle.api:app", host=settings.host, port=settings.port, reload=False)
