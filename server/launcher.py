"""Entry point for the packaged BiomarkerSearchServer.exe (see BUILD.md). Not used when running
from source — that path still uses `uvicorn server.main:app --reload` directly. This script
skips --reload (a dev-only file-watcher that isn't meaningful, and can misbehave, inside a
frozen executable) and prints plain-language status for someone reading a console window with
no coding background.
"""
import uvicorn

from server.main import app

if __name__ == "__main__":
    print("Starting Biomarker Search backend...")
    print("Once you see 'Application startup complete', open FDA510kBiomarkerSearch.html in your browser.")
    print("Leave this window open while you use the tool. Closing it stops the server.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
