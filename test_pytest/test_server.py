import asyncio

import pytest

from hat import aio
from hat import json
from hat import util
from hat.drivers import tcp
import hat.event.eventer
import hat.event.common

from hat.mariner import transport
import hat.mariner.server.server


@pytest.fixture
def mariner_addr():
    return tcp.Address('127.0.0.1', util.get_unused_tcp_port())


@pytest.fixture
def eventer_addr():
    return tcp.Address('127.0.0.1', util.get_unused_tcp_port())


@pytest.fixture
def conf(mariner_addr, eventer_addr):
    return {
        'mariner': {
            'host': mariner_addr.host,
            'port': mariner_addr.port},
        'eventer': {
            'host': eventer_addr.host,
            'port': eventer_addr.port,
            'token': None},
        'clients': []}


class MockEvenerClient(hat.event.eventer.Client):

    def __init__(self):
        self._async_group = aio.Group()
        self._status = hat.event.common.Status.OPERATIONAL

    @property
    def async_group(self):
        return self._async_group

    @property
    def status(self):
        return self._status

    async def register(self, events, with_response=False):
        pass

    async def query(self, params):
        pass


async def test_create(conf):
    server = await hat.mariner.server.server.create_server(conf)

    assert isinstance(server, hat.mariner.server.server.Server)
    assert server.is_open

    server.close()
    await server.wait_closing()
    assert server.is_closing
    await server.wait_closed()
    assert server.is_closed


async def test_connect(conf, mariner_addr):
    server = await hat.mariner.server.server.create_server(conf)

    conn = await transport.connect(mariner_addr)

    with pytest.raises(asyncio.TimeoutError):
        await aio.wait_for(conn.receive(), timeout=0.05)

    assert conn.info.remote_addr == mariner_addr

    await server.async_close()

    assert conn.is_closed


@pytest.mark.parametrize('status', hat.event.common.Status)
@pytest.mark.parametrize('client_token', [None, 'some random token...'])
async def test_init_success(conf, mariner_addr, status, client_token,
                            monkeypatch):

    async def mock_eventer_connect(**kwargs):
        client = MockEvenerClient()
        client._async_group = aio.Group()

        client._status = status
        return client

    client_name = 'cli1'
    subscriptions = []
    server_id = None
    persisted = False

    clients = [{'name': client_name,
                'token': client_token,
                'subscriptions': []}]
    conf = json.set_(conf, 'clients', clients)

    server = await hat.mariner.server.server.create_server(conf)

    monkeypatch.setattr(hat.event.eventer, "connect", mock_eventer_connect)
    conn = await transport.connect(mariner_addr)

    init_req = transport.InitReqMsg(
        client_name=client_name,
        client_token=client_token,
        subscriptions=subscriptions,
        server_id=server_id,
        persisted=persisted)

    await conn.send(init_req)

    init_resp = await conn.receive()
    assert isinstance(init_resp, transport.InitResMsg)
    assert init_resp.success
    assert init_resp.status == status
    assert init_resp.error is None

    await server.async_close()


@pytest.mark.parametrize('client_name, client_token, error', [
    ('unknown client', 'client token', 'invalid client name'),
    ('cli1', 'wrong token', 'invalid client token'),
    ])
async def test_init_failure(conf, mariner_addr, client_name, client_token,
                            error, monkeypatch):

    subscriptions = []
    server_id = None
    persisted = False

    clients = [{'name': 'cli1',
                'token': 'client token',
                'subscriptions': []}]
    conf = json.set_(conf, 'clients', clients)

    server = await hat.mariner.server.server.create_server(conf)

    monkeypatch.setattr(hat.event.eventer, "connect", MockEvenerClient())
    conn = await transport.connect(mariner_addr)

    init_req = transport.InitReqMsg(
        client_name=client_name,
        client_token=client_token,
        subscriptions=subscriptions,
        server_id=server_id,
        persisted=persisted)

    await conn.send(init_req)

    init_resp = await conn.receive()
    assert isinstance(init_resp, transport.InitResMsg)
    assert init_resp.success is False
    assert init_resp.status is None
    assert init_resp.error == error

    await conn.wait_closed()

    assert server.is_open

    await server.async_close()


async def test_eventer_connect(conf, mariner_addr, monkeypatch):
    clients_count = 10
    eventer_client_queue = aio.Queue()

    async def mock_eventer_connect(**kwargs):
        client = MockEvenerClient()
        client._kwargs = kwargs

        eventer_client_queue.put_nowait(client)
        return client

    clients_init_msgs = [
        transport.InitReqMsg(
            client_name=f"cli{i}",
            client_token=f"client token  {i}",
            subscriptions=[(str(i) for i in range(i))],
            server_id=i,
            persisted=bool(i % 2))
        for i in range(clients_count)]

    clients_conf = [{'name': i.client_name,
                     'token': i.client_token,
                     'subscriptions': []} for i in clients_init_msgs]
    conf = json.set_(conf, 'clients', clients_conf)

    server = await hat.mariner.server.server.create_server(conf)

    monkeypatch.setattr(hat.event.eventer, "connect", mock_eventer_connect)

    eventer_clients = []
    mariner_conns = []

    for init_msg, client_conf in zip(clients_init_msgs, clients_conf):
        mariner_conn = await transport.connect(mariner_addr)
        mariner_conns.append(mariner_conn)

        await mariner_conn.send(init_msg)

        init_resp = await mariner_conn.receive()
        assert init_resp.success
        assert init_resp.error is None

        eventer_client = await eventer_client_queue.get()
        eventer_clients.append(eventer_client)

        assert eventer_client._kwargs['addr'].host == conf['eventer']['host']
        assert eventer_client._kwargs['addr'].port == conf['eventer']['port']
        assert eventer_client._kwargs[
            'client_name'] == f"mariner - {init_msg.client_name}"
        assert (eventer_client._kwargs['client_token'] ==
                conf['eventer']['token'])
        assert set(eventer_client._kwargs['subscriptions']) == set(
                *init_msg.subscriptions,
                *client_conf['subscriptions'])
        assert eventer_client._kwargs['server_id'] == init_msg.server_id
        assert eventer_client._kwargs['persisted'] == init_msg.persisted

        assert mariner_conn.is_open

    for eventer_client, mariner_conn in zip(eventer_clients, mariner_conns):
        assert eventer_client.is_open
        assert mariner_conn.is_open

        eventer_client.close()
        await mariner_conn.wait_closed()

    assert server.is_open

    await server.async_close()
