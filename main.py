

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

origins = [
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Query(BaseModel):
    prompt: str
    stream: bool
    use_context: bool
    include_sources: bool

class Document(BaseModel):
    doc_name: str

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/get-file-list/")
async def route_ingested_list():
    return {"doc_list": [1,2,3]}

@app.post("/submit-query/")
async def route_query(query: Query):
    return query.prompt

@app.post("/delete/")
async def route_query(doc: Document):
    return doc