from pathlib import Path
from models import UserService
Path(__file__).with_name("EXECUTED.txt").write_text("executed")

def greet(name: str) -> str:
    service = UserService()
    return "Hello " + service.normalize(name)
