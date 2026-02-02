# backend
backend for app

.\.venv\Scripts\Activate.ps1 // turn on venv environment
uvicorn main:app --reload // TO RUN IN TERMINAL
http://127.0.0.1:8000/docs // ACCESS TO UI
Ctrl + C to stop program

## Running locally with Docker

1. **Start PostgreSQL**: `docker-compose up -d`
2. **Create `.env` file or copy from example**: `cp .env.example .env` 
3. **Create and activate python virtual environment (not required but recommended):** `python3 -m venv .venv && source .venv/bin/activate`
3. **Install dependencies**: `pip install -r requirements.txt`
4. **Run the app**: `uvicorn main:app --reload`
5. **Access the API**: http://localhost:8000/docs

