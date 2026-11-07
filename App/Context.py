# -*- coding: utf-8 -*-
"""전역 앱 참조.

HttpApi/Server/SelfTest 가 서로를 import 하면 순환이 생기므로,
"지금 실행 중인 App" 하나만 여기에 담아 두고 꺼내 쓴다.
"""


class _Context(object):
    def __init__(self):
        self.app = None

    def bind(self, app):
        """앱 인스턴스를 등록한다(SelfTest 는 임시 앱을 넣는다)."""
        self.app = app

    def get(self):
        return self.app

    def log(self, text):
        app = self.app
        if app is not None:
            app.sup.log(text)


CTX = _Context()
