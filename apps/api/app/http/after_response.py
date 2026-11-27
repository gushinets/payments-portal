"""Run explicitly deferred tasks after the final successful ASGI body send."""

from starlette.background import BackgroundTasks
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AfterResponseTasksMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        successful = False

        async def send_then_run(message: Message) -> None:
            nonlocal successful
            await send(message)
            if message["type"] == "http.response.start":
                successful = 200 <= message["status"] < 300
            elif successful and message["type"] == "http.response.body" and not message.get("more_body", False):
                tasks: BackgroundTasks | None = scope.get("state", {}).pop("after_response_tasks", None)
                if tasks is not None:
                    await tasks()

        await self.app(scope, receive, send_then_run)
