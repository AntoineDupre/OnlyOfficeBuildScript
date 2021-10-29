import asyncio
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

host = "192.168.1.54"
port = 8080


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

    @property
    def connected(self):
        """ is connection established """
        return self.ws and self.reader and self.writer

    async def connect(self):
        """ Connect to docserver"""
        logging.debug("Connecting TCP")
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        logging.debug("Connection WS")
        self.ws = WSConnection(ConnectionType.CLIENT)
        await self.send_request()
        await self._recieve_from_docserver()
        await self.handle_message()

    async def _send_to_docserver(self, data):
        """ Send data to the docserver """
        logging.debug("Sending {} bytes".format(len(data)))
        self.writer.write(data)
        await self.writer.drain()
        logging.debug("Sent")


    async def _recieve_from_docserver(self):
        """ Read data from the docserver ws """
        in_data = await self.reader.read(1024)
        if not in_data:
            logging.debug("Received 0 bytes (connection closed)")
            self.ws.receive_data(None)
        else:
            logging.debug("Received {} bytes".format(len(in_data)))
            self.ws.receive_data(in_data)

    async def send_message(self, message):
        """ Send message to docserver """
        logging.debug("Sending message ...")
        data = self.ws.send(Message(data=message))
        await self._send_to_docserver(data)

    async def send_request(self):
        """ Send connection request to the docserver"""
        logging.debug(f"Sending connection request to {self.target}...")
        request = self.ws.send(Request(host=self.host, target=self.target))
        await self._send_to_docserver(request)

    async def pong(self):
        """ Send pong reply"""
        logging.debug("Sending Pong ...")
        pong = self.ws.send(Pong(payload=b""))
        await self._send_to_docserver(pong)

    async def handle_message(self):
        """ Handle incomming events"""
        if self.connected:
            for event in self.ws.events():
                logging.debug(f"Recieved event {type(event)}")
                if isinstance(event, Ping):
                    await self.pong()
                elif isinstance(event, CloseConnection):
                    self.ws = None
                    self.reader = None
                    self.writer = None
                    self.running = False
                    return
                elif isinstance(event, AcceptConnection):
                    logging.debug("Accepted Connection")
                else:
                    self.event_queue.put_nowait(event.data)

    async def client_loop(self):
        """ Loop over incoming messages"""
        logging.info("Client loop Listening")

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
    cors = aiohttp_cors.setup(app)

    # Synchronise event from onlyoffice to docserver with a queue
    from_ooclient_to_docserver = asyncio.Queue()
    from_docserver_to_ooclient = asyncio.Queue()
    # Create doc server interface
    doc_interface = DocServerInterface("localhost", 8000, "/doc/-5365490046783702160/c", from_docserver_to_ooclient , app)

    # Setup server interface for onlyoffice client
    async def msg_handler(msg, session):
        """ Handle messages comming from onlyoffice client"""
        logging.debug(f"Onlyoffice client message handler {session} -  {msg}")
        if session.manager is None:
            return
        if msg.type == sockjs.MSG_OPEN:
            logging.debug("Onlyoffice Client Interface: Get connection")
            await doc_interface.connect()
        elif msg.type == sockjs.MSG_MESSAGE:
            logging.debug("Onlyoffice Client Interface: Get message")
            from_ooclient_to_docserver.put_nowait(msg.data)
        elif msg.type == sockjs.MSG_CLOSED:
            logging.debug("Onlyoffice Client Interface: Close")
        else:
            logging.debug(f"OnlyOffice Client Interface: Unknown msg type {msg.type}")

    sockjs.add_endpoint(app, msg_handler, name="TEST", prefix="/maninthemiddle")
    # Setup routes
    for r in app.router.routes():
        try:
            cors.add(r)
        except ValueError as e:
            pass

    doc_serv_dir = "./DocumentServer/build_tools/out/linux_64/onlyoffice/documentserver"
    statics = [ "/fonts", "/sdkjs", "/web-apps", "/sdkjs-plugins", "/dictionaries"]
    for route in statics:
        app.router.add_routes([web.static(route, doc_serv_dir + route)])
    app.router.add_routes([web.static('/info', doc_serv_dir + '/server/info')])

    # Background task
    async def docserver_event_loop():
        """ Loop over Docservice events"""
        await doc_interface.client_loop()

    async def forward_client_events():
        """ Loop over Onlyoffice client events"""
        while True:
            read = await from_ooclient_to_docserver.get()
            logging.debug("Forwarding onlyoffice client message")
            from_ooclient_to_docserver.task_done()
            # Forward message
            await doc_interface.send_message(read)

    async def forward_docserver_events():
        while True:
            read = await from_docserver_to_ooclient.get()
            logging.debug("Forwarding docserver message")
            from_docserver_to_ooclient.task_done()
            manager = sockjs.get_manager("TEST", app)
            if len(read) > 1:
                manager.broadcast(read[1:])



    loop = asyncio.get_event_loop()
    doc_server_task = loop.create_task(docserver_event_loop())
    forward_client_event_task = loop.create_task(forward_client_events())
    forward_docserver_event_task = loop.create_task(forward_docserver_events())

    # Start ws server
    handler = app.make_handler(debug=True)
    f = loop.create_server(handler, "0.0.0.0", 8001)
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
