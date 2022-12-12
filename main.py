import asyncio
import configparser
import flask
import json
import threading
import time
import websockets


class LavalinkWSClient:
    def __init__(self, node_name: str, host: str, port: int, password: str, user_id: int, secure: bool = False, quiet: bool = False):
        if secure:
            self.uri = 'wss://{}:{}'.format(host, port)
        else:
            self.uri = 'ws://{}:{}'.format(host, port)
        self.node_name = node_name
        self.password = password
        self.user_id = user_id
        self.stats_raw = {}
        self.stats_timestamp = 0
        self.quiet = quiet
        self.ws = None
    
    @property
    def stats(self) -> dict:
        return {
            'stats': self.stats_raw,
            'timestamp': self.stats_timestamp
        }
    
    def _log(self, msg: str):
        if not self.quiet:
            print('[{0}] {1}'.format(self.node_name, msg))
    
    async def connect(self):
        self._log('Connecting to Lavalink'.format(self.node_name))
        try:
            self.ws = await websockets.connect(
                self.uri,
                extra_headers={
                    'Authorization': self.password,
                    'User-Id': str(self.user_id),
                    'Client-Name': 'lavalink-stats'
                }
            )
        except websockets.exceptions.InvalidStatusCode as e:
            print('[{0}] Could not connect to Lavalink'.format(self.node_name), e)
            return
        else:
            self._log('[{0}] Connected to Lavalink'.format(self.node_name))
        
        async for msg in self.ws:
            self._log('[{0}] Received message: {1}'.format(self.node_name, msg))
            try:
                msg = json.loads(msg)
            except Exception as e:
                print('[{0}] Could not parse message'.format(self.node_name), e)
            else:
                if msg['op'] == 'stats':
                    self.stats_raw = msg
                    self.stats_timestamp = int(time.time() * 1000)
    
        self._log('[{0}] Connection closed'.format(self.node_name))
    
    def receive_thread(self, loop: asyncio.AbstractEventLoop):
        coro = self.connect()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        future.result()
        if not self.quiet:
            print('[{0}] Closed thread'.format(self.node_name))


# Read config file
config = configparser.ConfigParser()
config.read('config.ini')
try:
    flask_config = config['config']
except KeyError:
    raise Exception('Missing [config] section from config file')


# Create a WebSocket client for each config section
clients = {}
for section in config.sections():
    # Disallow duplicate node names
    if section in clients:
        raise Exception('Duplicate node name: {}'.format(section))
    
    # Ignore Flask config
    if section == 'config':
        continue
    
    client = LavalinkWSClient(
        node_name=section,
        host=config[section]['host'],
        port=int(config[section]['port']),
        password=config[section]['password'],
        user_id=int(config[section]['user_id']),
        secure=config[section].getboolean('secure', fallback=False),
        quiet=flask_config.getboolean('quiet', fallback=False)
    )
    clients[section] = client


# Create Flask app
app = flask.Flask(__name__)
@app.route('/stats/<node>')
def stats(node):
    if node not in clients:
        return flask.jsonify({'error': 'Invalid node name'}), 404
    return flask.jsonify(clients[node].stats)


# Thread for event loop
def run_event_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


# Start WebSocket clients and create threads for each one
if __name__ == '__main__':
    # Create event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for client in clients.values():
        thread = threading.Thread(target=client.receive_thread, args=(loop,), daemon=True)
        thread.start()
    
    # Start event loop
    thread = threading.Thread(target=run_event_loop, args=(loop,), daemon=True)
    thread.start()
    
    # Start Flask app
    app.run(host=flask_config['host'], port=int(flask_config['port']))