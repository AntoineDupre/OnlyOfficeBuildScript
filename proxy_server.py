import asyncio
import json
import logging

from aiohttp import web
from wsproto import WSConnection
from wsproto.connection import ConnectionType
from wsproto.events import (
    AcceptConnection,
    CloseConnection,
    Message,
    Ping,
    Pong,
    Request,
    TextMessage,
)

import aiohttp_cors
import sockjs

docserver_host = "localhost"
docserver_port = 8000
docid = "305276599151020007"
docid = "946950236676322061"
doc_serv_dir = "./DocumentServer/build_tools/out/linux_64/onlyoffice/documentserver"

client_interface = "0.0.0.0"
client_interface_port = 8001


COLOR_1 = "\033[33m"
COLOR_2 = "\033[34m"
COLOR_3 = "\033[35m"
RESET = "\033[0m"


def log_it(color, message):
    logging.debug(color + message + RESET)


class DocServerInterface:
    """ Ws connected to the onlyoffice docserver"""

    def __init__(self, host, port, target, event_queue, app):
        self.host = host
        self.port = port
        self.target = target + "/782/6goqo0e2/websocket"
        self.reader = None
        self.writer = None
        self.ws = None
        self.running = False
        self.event_queue = event_queue
        self.app = app

    def logging(self, message):
        logging.debug("\033[36m" + message + "\033[0m")

    @property
    def connected(self):
        """ is connection established """
        return self.ws and self.reader and self.writer

    async def connect(self):
        """ Connect to docserver"""
        self.logging("Connecting TCP")
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.logging("Connection WS")
        self.ws = WSConnection(ConnectionType.CLIENT)
        await self.send_request()
        await self._recieve_from_docserver()
        await self.handle_message()

    async def _send_to_docserver(self, data):
        """ Send data to the docserver """
        self.logging("Sending {} bytes".format(len(data)))
        self.writer.write(data)
        await self.writer.drain()
        self.logging("Sent")

    async def send_sockjs_message(self, data):
        message = json.dumps([data])
        await self.send_message(message)

    async def _recieve_from_docserver(self):
        """ Read data from the docserver ws """
        in_data = await self.reader.read(1024)
        if not in_data:
            self.logging("Received 0 bytes (connection closed)")
            self.ws.receive_data(None)
        else:
            self.logging("Received {} bytes".format(len(in_data)))
            self.ws.receive_data(in_data)

    async def send_message(self, message):
        """ Send message to docserver """
        self.logging("Sending message ...")
        data = self.ws.send(Message(data=message))
        await self._send_to_docserver(data)

    async def send_request(self):
        """ Send connection request to the docserver"""
        self.logging(f"Sending connection request to {self.target}...")
        request = self.ws.send(Request(host=self.host, target=self.target))
        await self._send_to_docserver(request)

    async def pong(self):
        """ Send pong reply"""
        self.logging("Sending Pong ...")
        pong = self.ws.send(Pong(payload=b""))
        await self._send_to_docserver(pong)

    async def handle_message(self):
        """ Handle incomming events"""
        if self.connected:
            for event in self.ws.events():
                self.logging(f"Recieved event {type(event)}")
                self.logging(f"Event {event}")
                if isinstance(event, Ping):
                    await self.pong()
                elif isinstance(event, CloseConnection):
                    self.ws = None
                    self.reader = None
                    self.writer = None
                    self.running = False
                    return
                elif isinstance(event, AcceptConnection):
                    self.logging("Accepted Connection")
                else:
                    self.event_queue.put_nowait(event.data)

    async def client_loop(self):
        """ Loop over incoming messages"""
        self.logging("Client loop Listening")

        self.running = True
        while self.running:
            if not self.connected:
                await asyncio.sleep(0.1)
                continue
            try:
                await self._recieve_from_docserver()
                await self.handle_message()
                await asyncio.sleep(0.1)
            except Exception as e:
                print(e)


def run_app():
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s"
    )

    # Create application
    app = web.Application()
    cors = aiohttp_cors.setup(app, )

    # Synchronise event from onlyoffice to docserver with a queue
    from_ooclient_to_docserver = asyncio.Queue()
    from_docserver_to_ooclient = asyncio.Queue()
    # Create doc server interface
    doc_interface = DocServerInterface(
        docserver_host,
        docserver_port,
        f"/doc/{docid}/c",
        from_docserver_to_ooclient,
        app,
    )

    # Setup server interface for onlyoffice client
    async def msg_handler(msg, session):
        """ Handle messages comming from onlyoffice client"""
        log_it(COLOR_1, f"Onlyoffice client message handler {session} -  {msg}")
        if session.manager is None:
            return
        if msg.type == sockjs.MSG_OPEN:
            log_it(COLOR_1, "Onlyoffice Client Interface: Get connection")
            await doc_interface.connect()
        elif msg.type == sockjs.MSG_MESSAGE:
            log_it(COLOR_1, "Onlyoffice Client Interface: Get message")
            from_ooclient_to_docserver.put_nowait(msg.data)
        elif msg.type == sockjs.MSG_CLOSED:
            log_it(COLOR_1, "Onlyoffice Client Interface: Close")
        else:
            log_it(COLOR_1, f"OnlyOffice Client Interface: Unknown msg type {msg.type}")


    async def handler(request):
        url = request.url
        import aiohttp
        url = str(url).replace(f"localhost:{client_interface_port}/cache/", f"localhost:{docserver_port}/cache/")
        # url = "http://localhost/cache/files/946950236676322061/Editor.bin/Editor.bin?md5=vgREpCQt5JWdZksn3F3Gbg&expires=1638706094&filename=Editor.bin"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.read()
        return web.Response(content_type=resp.content_type, body=data, headers={"Access-Control-Allow-Origin": "*"})

    app.router.add_route("GET", "/cache/{tail:.*}", handler)



    end_point = "/doc/[0-9-.a-zA-Z_=]*/c"
    # sockjs.add_endpoint(app, msg_handler, name="TEST", prefix=end_point)
    sockjs.add_endpoint(app, msg_handler, name="TEST", prefix="/maninthemiddle")
    # Setup routes
    for r in app.router.routes():
        try:
            cors.add(r)
        except ValueError as e:
            pass

    statics = ["/fonts", "/sdkjs", "/web-apps", "/sdkjs-plugins", "/dictionaries"]
    for route in statics:
        app.router.add_routes([web.static(route, doc_serv_dir + route)])
    app.router.add_routes([web.static("/info", doc_serv_dir + "/server/info")])



    # Background task
    async def docserver_event_loop():
        """ Loop over Docservice events"""
        await doc_interface.client_loop()

    async def forward_client_events():
        """ Loop over Onlyoffice client events"""
        while True:
            read = await from_ooclient_to_docserver.get()
            log_it(COLOR_2, "Forwarding onlyoffice client message")
            from_ooclient_to_docserver.task_done()
            # Forward message
            await doc_interface.send_sockjs_message(read)

            # await doc_interface.send_message(read)

    async def forward_docserver_events():
        while True:
            read = await from_docserver_to_ooclient.get()
            log_it(COLOR_3, "Forwarding docserver message")
            from_docserver_to_ooclient.task_done()
            notify_client(read)

    def notify_client(message):
        if len(message) <= 1 or message[0] != "a":
            return
        manager = sockjs.get_manager("TEST", app)
        for session in manager.values():
            if not session.expired:

                message = message.replace("localhost/cache/", "localhost:8001/cache/")
                session.send_frame(message)

    loop = asyncio.get_event_loop()
    doc_server_task = loop.create_task(docserver_event_loop())
    forward_client_event_task = loop.create_task(forward_client_events())
    forward_docserver_event_task = loop.create_task(forward_docserver_events())

    # Start ws server
    handler = app.make_handler(debug=True)
    f = loop.create_server(handler, client_interface, client_interface_port)
    srv = loop.run_until_complete(f)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("Ctrl-C was pressed")
    finally:
        loop.run_until_complete(handler.shutdown())
        srv.close()
        loop.run_until_complete(srv.wait_closed())
        loop.run_until_complete(app.cleanup())
    loop.close()


if __name__ == "__main__":
    run_app()
