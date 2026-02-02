# Backend
<!-- backend for app

Setup(in order):

python -m venv .venv // creates .venv folder

create new .env file in the root of the project and insert:  
DATABASE_URL = postgresql+psycopg://postgres:PASSWORD@localhost:5432/sana //Replace PASSWORD with the password you want to use  
PSYCOPG_PREFER_PQ_BINARY=1  
SECRET_KEY = generatedKey // gerate key via "openssl rand -hex 32"
ALGORITHM = HS256  
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pip install -r requirements.txt // installs all required dependencies

alembic upgrade head // creates/updates database using newest migration version

(if alembic upgrade fails with no pq wrapper available then ensure "PATH/TO/Postgres/VerNo/bin" is added to path for example mine is :C/Program Files/PostreSQL/17/bin but yours may be different) 


(Make sure postgreSQL is running to use the database)
To run:
.\.venv\Scripts\Activate.ps1 // turn on venv environment  
uvicorn main:app --reload // TO RUN IN TERMINAL  
http://127.0.0.1:8000/docs // ACCESS TO UI  
Ctrl + C to stop program -->

## Running locally with Docker

1. **Start PostgreSQL**: `docker-compose up -d`

2. **Create `.env` file or copy from example**:
   - Linux/Mac: `cp .env.example .env`
   - Windows: `copy .env.example .env`

3. **Generate SECRET_KEY**: `openssl rand -hex 32` and add the output to your `.env` file

4. **Create and activate python virtual environment**:
   - Linux/Mac: `python3 -m venv .venv && source .venv/bin/activate`
   - Windows (CMD): `python -m venv .venv && .venv\Scripts\activate.bat`
   - Windows (PowerShell): `python -m venv .venv && .venv\Scripts\Activate.ps1`

5. **Install dependencies**: `pip install -r requirements.txt`

6. **Run migrations**: `alembic upgrade head`

7. **Run the app**: `uvicorn main:app --reload`

8. **Access the API**: http://localhost:8000/docs



