"""Production WSGI entry point: gunicorn -w 4 -b 0.0.0.0:8000 wsgi:application"""
import os
from dotenv import load_dotenv
load_dotenv()
from app import create_app
application = create_app(os.environ.get("FLASK_ENV", "production"))
if __name__ == "__main__":
    application.run()
