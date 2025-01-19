
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

chat_server = 'localhost:8080'


'''
Controls which servers can access the router.
'''
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
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
    get_docs = http.client.HTTPConnection(chat_server)
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
    h1 = http.client.HTTPConnection(chat_server)
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
    response = obj["choices"][0]["message"]["content"] 
    out = {}
    out['response'] = response
    out['sources'] = {}
    for data in obj["choices"][0]["sources"]:
        out['sources'][data["document"]["doc_metadata"]["file_name"]] = data["text"]
    return out


'''
Given a document id, deletes the associated document from the server.

Returns confirmation object that the document with the associated 
document id has been deleted from the server.
'''
@app.post("/delete/")
async def delete_file(doc: Document):
    conn = http.client.HTTPConnection(chat_server)
    try:
        endpoint = f"/v1/ingest/{doc.doc_id}"
        conn.request("DELETE", endpoint)
        response = conn.getresponse()

        if response.status == 200:
            return {"document deleted": doc.doc_id}
        else:
            return {"error": f"Failed to delete document: {response.status} {response.reason}"}
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}
    finally:
        conn.close()

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
    os.rename(tmp1.name,file_name)
    add_file("./" + file_name)
    os.remove(file_name)
    
    return {"upload_status": "successful"}


@app.post("/upload-and-process-pdf/")
async def create_upload_file(file: UploadFile):
    file_name = file.filename
    file_data = file.file.read()
    file_ext = file_name.split(".")[-1]
    tmp1 = tempfile.NamedTemporaryFile(dir=".", suffix=file_ext, delete=False)
    with open(tmp1.name, 'wb') as fout:
        fout.write(file_data) 

    if (file_ext == "pdf"):
        try:
            ## convert to markdown
            tmp2 = tempfile.NamedTemporaryFile(dir=".", suffix=".md", delete=False)
            md_data = pymupdf4llm.to_markdown(tmp1.name)
            pathlib.Path(tmp2.name).write_bytes(md_data.encode())
            md_name = file_name.split(".")[0] + ".md"
            os.rename(tmp2.name,md_name)
            add_file("./" + md_name)
            os.remove(md_name)
            os.remove(tmp1.name)
        except:
            return {"error": "File could not be converted"}
    else:
        return {"error": "File is not in pdf format"}

'''
Helper function for create_upload_file
'''
def add_file(fp):
    file = {'file': open(fp, 'rb')}
    ## using http.client will require direct setting of the payload, use requests.post instead!
    response = requests.post('http://' + chat_server + '/v1/ingest/file', files=file)
    