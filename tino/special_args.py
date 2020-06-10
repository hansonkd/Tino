class Auth:
    def __init__(self, auth_state):
        self.value = auth_state


class AuthRequired:
    def __init__(self, auth_state):
        self.value = auth_state


class ConnState:
    def __init__(self, value):
        self.value = value
