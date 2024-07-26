
from typing import Annotated
from fastapi import FastAPI, UploadFile
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

import pymupdf4llm
import pathlib
import tempfile
import os
import requests
import logging
import http
import json

logger = logging.getLogger(__name__)

app = FastAPI()

server = "http://localhost:8001"


'''
Controls which servers can access the router.
'''
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

'''
Query represents the expected json object structure
sent by the client during query submission.
'''
class Query(BaseModel):
    prompt: str
    stream: bool
    use_context: bool
    include_sources: bool

'''
Document represents the expected json object structure
sent by the client during document deletion.
'''
class Document(BaseModel):
    doc_id: str

'''
Returns a response containing a dictionary of file names to an list 
of their associated document ids. The server breaks down files into
one or more documents during ingestion. 
'''
@app.get("/get-file-list/")
async def route_ingested_list():
    get_docs = http.client.HTTPConnection('localhost:8001')
    get_docs.request("GET", "/v1/ingest/list")
    doc_ids = get_docs.getresponse()
    obj = json.loads(doc_ids.read())
    doc_list = list(
        map(lambda x: (x["doc_id"], 
                       x["doc_metadata"]["file_name"]), obj["data"]))
    doc_dict = {}
    for pair in doc_list:
        if pair[1] not in doc_dict:
            doc_dict[pair[1]] = []
        doc_dict[pair[1]].append(pair[0])
    return {"file_list": doc_dict}

'''
Given a query, sends a request for model response from the server.
The response type is governed by the elements in Query.

Returns a string response containing the response as well as 
referenced sources, delimited by the section delimiter.
'''
@app.post("/submit-query/")
async def route_query(query: Query):
    dct = {"prompt": query.prompt,
        "stream": query.stream,
        "use_context": query.use_context,
        "include_sources": query.include_sources}
    
    json_string = json.dumps(dct)
    h1 = http.client.HTTPConnection('localhost:8001')
    h1.request("POST", "/v1/completions", headers={"Content-Type": "application/json"}, body=json_string)
    response = h1.getresponse()
    
    if (response.status == 200):
        
        output = response.read()
        # converts output into json
        json_format = json.loads(output)
        
        # trims off useless outputs and zips possible responses with their sources in a json object.
        return response_parser(json_format)
    else:
        print("something went wrong!")

'''
Helper function for route_query
'''
def response_parser(obj: dict):
    section_delimiter = "\n\n===========================================================\n\n"
    response = obj["choices"][0]["message"]["content"] 
    for data in obj["choices"][0]["sources"]:
        response += section_delimiter
        response += data["document"]["doc_metadata"]["file_name"]
        response += section_delimiter
        response += data["text"]
    return response


'''
Given a document id, deletes the associated document from the server.

Returns confirmation object that the document with the associated 
document id has been deleted from the server.
'''
@app.post("/delete/")
async def delete_file(doc: Document):
    requests.delete("http://localhost:8001/v1/ingest/" + doc.doc_id)
    return {"document deleted" : doc.doc_id}

'''
Given a file, uploads the file to the server. If the file is in pdf format,
the file will be converted into the more parseable markdown format using
pymu4pdfllm library. Consider adding other pre-processing to this function.

Returns confirmation that the file has been uploaded is successful.
'''
@app.post("/upload-document/")
async def create_upload_file(file: UploadFile):
    file_name = file.filename
    file_data = file.file.read()
    file_ext = file_name.split(".")[-1]
    tmp1 = tempfile.NamedTemporaryFile(dir=".", suffix=file_ext, delete=False)
    with open(tmp1.name, 'wb') as fout:
        fout.write(file_data) 

    if (file_ext == "pdf"):
        ## convert to markdown
        tmp2 = tempfile.NamedTemporaryFile(dir=".", suffix=".md", delete=False)
        md_data = pymupdf4llm.to_markdown(tmp1.name)
        pathlib.Path(tmp2.name).write_bytes(md_data.encode())
        md_name = file_name.split(".")[0] + ".md"
        os.rename(tmp2.name,md_name)
        add_file("./" + md_name)
        os.remove(md_name)
        os.remove(tmp1.name)
    else:
        os.rename(tmp1.name,file_name)
        add_file("./" + file_name)
        os.remove(file_name)
    
    return {"upload_status": "successful"}

'''
Helper function for create_upload_file
'''
def add_file(fp):
    file = {'file': open(fp, 'rb')}
    response = requests.post('http://localhost:8001/v1/ingest/file', files=file)
    