class UserService:
    def normalize(self, name: str) -> str:
        return name.strip().title()
