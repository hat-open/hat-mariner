import itertools
import math
import typing

from hat import aio
from hat import json
from hat.drivers import tcp

from hat.mariner.transport import common
from hat.mariner.transport import encoder


ConnectionCb: typing.TypeAlias = aio.AsyncCallable[['Connection'], None]


async def connect(addr: tcp.Address,
                  **kwargs
                  ) -> 'Connection':
    conn = await tcp.connect(addr, **kwargs)

    return Connection(conn)


async def listen(connection_cb: ConnectionCb,
                 addr: tcp.Address,
                 **kwargs
                 ) -> tcp.Server:

    async def on_connection(conn):
        await aio.call(connection_cb, Connection(conn))

    srv = await tcp.listen(on_connection, addr, **kwargs)

    return srv


class Connection(aio.Resource):

    def __init__(self, conn: tcp.Connection):
        self._conn = conn

    @property
    def async_group(self) -> aio.Group:
        return self._conn.async_group

    @property
    def info(self) -> tcp.ConnectionInfo:
        return self._conn.info

    async def drain(self):
        await self._conn.drain()

    async def send(self, msg: common.Msg):
        msg_json = encoder.encode_msg(msg)
        msg_bytes = json.encode(msg_json).encode()
        msg_len = len(msg_bytes)
        len_size = math.ceil(msg_len.bit_length() / 8)

        if len_size < 1 or len_size > 8:
            raise ValueError('unsupported msg size')

        data = bytes(itertools.chain([len_size],
                                     msg_len.to_bytes(len_size, 'big'),
                                     msg_bytes))
        await self._conn.write(data)

    async def receive(self) -> common.Msg:
        len_size_bytes = await self._conn.readexactly(1)
        len_size = len_size_bytes[0]

        if len_size < 1 or len_size > 8:
            raise ValueError('unsupported msg size')

        msg_len_bytes = await self._conn.readexactly(len_size)
        msg_len = int.from_bytes(msg_len_bytes, 'big')

        msg_bytes = await self._conn.readexactly(msg_len)
        msg_str = str(msg_bytes, encoding='utf-8')
        msg_json = json.decode(msg_str)

        return encoder.decode_msg(msg_json)
