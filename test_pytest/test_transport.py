import pytest

from hat import aio
from hat import util

from hat.drivers import tcp
import hat.event.common

from hat.mariner import transport


# TODO
events = []

# TODO
register_events = []

# TODO
query_params = []

msgs = [
    transport.InitReqMsg(client_name='name',
                         client_token=None,
                         subscriptions=[],
                         server_id=None,
                         persisted=False),

    transport.InitReqMsg(client_name='name',
                         client_token='token',
                         subscriptions=[('a', 'b', 'c')],
                         server_id=123,
                         persisted=True),

    transport.InitResMsg(success=True,
                         status=hat.event.common.Status.OPERATIONAL,
                         error=None),

    transport.InitResMsg(success=False,
                         status=None,
                         error='error'),

    transport.StatusMsg(status=hat.event.common.Status.STANDBY),

    transport.StatusMsg(status=hat.event.common.Status.OPERATIONAL),

    transport.EventsMsg(events=[]),

    transport.EventsMsg(events=events),

    transport.RegisterReqMsg(register_id=123,
                             register_events=[]),

    transport.RegisterReqMsg(register_id=321,
                             register_events=register_events),

    transport.RegisterResMsg(register_id=123,
                             success=True,
                             events=events),

    transport.RegisterResMsg(register_id=321,
                             success=False,
                             events=None),

    *(transport.QueryReqMsg(query_id=query_id,
                            params=params)
      for query_id, params in enumerate(query_params)),

    transport.QueryResMsg(
        query_id=123,
        result=hat.event.common.QueryResult(events=[],
                                            more_follows=False)),

    transport.QueryResMsg(
        query_id=321,
        result=hat.event.common.QueryResult(events=events,
                                            more_follows=True)),

    transport.PingReqMsg(ping_id=123),

    transport.PingResMsg(ping_id=321)
]


def assert_msg_equal(msg1, msg2):
    msgs = [msg1, msg2]

    for i, msg in enumerate(list(msgs)):
        if isinstance(msg, transport.InitReqMsg):
            msgs[i] = msg._replace(subscriptions=list(msg.subscriptions))

        elif isinstance(msg, transport.EventsMsg):
            msgs[i] = msg._replace(events=list(msg.events))

        elif isinstance(msg, transport.RegisterReqMsg):
            msgs[i] = msg._replace(register_events=list(msg.register_events))

        elif isinstance(msg, transport.RegisterResMsg):
            if msg.events is not None:
                msgs[i] = msg._replace(events=list(msg.events))

        elif isinstance(msg, transport.QueryReqMsg):
            if (isinstance(msg.params,
                           (hat.event.common.QueryLatestParams,
                            hat.event.common.QueryTimeseriesParams)) and
                    msg.params.event_types is not None):
                params = msg.params._replace(
                    event_types=list(msg.params.event_types))
                msgs[i] = msg._replace(params=params)

        elif isinstance(msg, transport.QueryResMsg):
            result = msg.result._replace(events=list(msg.result.events))
            msgs[i] = msg._replace(result=result)

    assert msgs[0] == msgs[1]


@pytest.fixture
def addr():
    return tcp.Address('127.0.0.1', util.get_unused_tcp_port())


@pytest.mark.parametrize('msg', msgs)
async def test_send_receive(addr, msg):
    conn_queue = aio.Queue()

    srv = await transport.listen(conn_queue.put_nowait, addr)
    conn1 = await transport.connect(addr)
    conn2 = await conn_queue.get()

    await conn1.send(msg)
    received_msg = await conn2.receive()
    assert_msg_equal(msg, received_msg)

    await conn2.send(msg)
    received_msg = await conn1.receive()
    assert_msg_equal(msg, received_msg)

    await conn1.async_close()
    await conn2.async_close()
    await srv.async_close()
