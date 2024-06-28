import base64

from hat import json
import hat.event.common

from hat.mariner.transport import common


def encode_msg(msg: common.Msg) -> json.Data:
    if isinstance(msg, common.InitReqMsg):
        return _encode_init_req_msg(msg)

    if isinstance(msg, common.InitResMsg):
        return _encode_init_res_msg(msg)

    if isinstance(msg, common.StatusMsg):
        return _encode_status_msg(msg)

    if isinstance(msg, common.EventsMsg):
        return _encode_events_msg(msg)

    if isinstance(msg, common.RegisterReqMsg):
        return _encode_register_req_msg(msg)

    if isinstance(msg, common.RegisterResMsg):
        return _encode_register_res_msg(msg)

    if isinstance(msg, common.QueryReqMsg):
        return _encode_query_req_msg(msg)

    if isinstance(msg, common.QueryResMsg):
        return _encode_query_res_msg(msg)

    if isinstance(msg, common.PingReqMsg):
        return _encode_ping_req_msg(msg)

    if isinstance(msg, common.PingResMsg):
        return _encode_ping_res_msg(msg)

    raise ValueError('unsupported msg type')


def decode_msg(msg: json.Data) -> common.Msg:
    if msg['msg_type'] == 'init_req':
        return _decode_init_req_msg(msg)

    if msg['msg_type'] == 'init_res':
        return _decode_init_res_msg(msg)

    if msg['msg_type'] == 'status':
        return _decode_status_msg(msg)

    if msg['msg_type'] == 'events':
        return _decode_events_msg(msg)

    if msg['msg_type'] == 'register_req':
        return _decode_register_req_msg(msg)

    if msg['msg_type'] == 'register_res':
        return _decode_register_res_msg(msg)

    if msg['msg_type'] == 'query_req':
        return _decode_query_req_msg(msg)

    if msg['msg_type'] == 'query_res':
        return _decode_query_res_msg(msg)

    if msg['msg_type'] == 'ping_req':
        return _decode_ping_req_msg(msg)

    if msg['msg_type'] == 'ping_res':
        return _decode_ping_res_msg(msg)

    raise Exception('invalid msg type')


def _encode_init_req_msg(msg):
    return {'msg_type': 'init_req',
            'client_name': msg.client_name,
            'client_token': msg.client_token,
            'subscriptions': [_encode_event_type(event_type)
                              for event_type in msg.subscriptions],
            'server_id': msg.server_id,
            'persisted': msg.persisted}


def _decode_init_req_msg(msg):
    client_name = msg['client_name']
    if not isinstance(client_name, str):
        raise Exception('invalid client name')

    client_token = msg['client_token']
    if client_token is not None and not isinstance(client_token, str):
        raise Exception('invalid client token')

    subscriptions = [_decode_event_type(event_type)
                     for event_type in msg['subscriptions']]

    server_id = msg['server_id']
    if server_id is not None and not isinstance(server_id, int):
        raise Exception('invalid server id')

    persisted = msg['persisted']
    if not isinstance(persisted, bool):
        raise Exception('invalid persisted')

    return common.InitReqMsg(client_name=client_name,
                             client_token=client_token,
                             subscriptions=subscriptions,
                             server_id=server_id,
                             persisted=persisted)


def _encode_init_res_msg(msg):
    msg_json = {'msg_type': 'init_res',
                'success': msg.success}

    if msg.success:
        if msg.status is None:
            raise ValueError('unsupported status')

        msg_json['status'] = msg.status.name

    else:
        if msg.error is None:
            raise ValueError('unsupported error')

        msg_json['error'] = msg.error

    return msg_json


def _decode_init_res_msg(msg):
    success = msg['success']
    if not isinstance(success, bool):
        raise Exception('invalid success')

    if success:
        status = hat.event.common.Status[msg['status']]
        error = None

    else:
        status = None
        error = msg['error']
        if not isinstance(error, str):
            raise Exception('invalid error')

    return common.InitResMsg(success=success,
                             status=status,
                             error=error)


def _encode_status_msg(msg):
    return {'msg_type': 'status',
            'status': msg.status.name}


def _decode_status_msg(msg):
    return common.StatusMsg(status=hat.event.common.Status[msg['status']])


def _encode_events_msg(msg):
    return {'msg_type': 'events',
            'events': [_encode_event(event) for event in msg.events]}


def _decode_events_msg(msg):
    return common.EventsMsg(events=[_decode_event(event)
                                    for event in msg['events']])


def _encode_register_req_msg(msg):
    return {'msg_type': 'register_req',
            'register_id': msg.register_id,
            'register_events': [_encode_register_event(register_event)
                                for register_event in msg.register_events]}


def _decode_register_req_msg(msg):
    register_id = msg['register_id']
    if not isinstance(register_id, int):
        raise Exception('invalid register id')

    register_events = [_decode_register_event(register_event)
                       for register_event in msg['register_events']]

    return common.RegisterReqMsg(register_id=register_id,
                                 register_events=register_events)


def _encode_register_res_msg(msg):
    msg_json = {'msg_type': 'register_res',
                'register_id': msg.register_id,
                'success': msg.success}

    if msg.success:
        if msg.events is None:
            raise ValueError('unsupported events')

        msg_json['events'] = [_encode_event(event) for event in msg.events]

    return msg_json


def _decode_register_res_msg(msg):
    register_id = msg['register_id']
    if not isinstance(register_id, int):
        raise Exception('invalid register id')

    success = msg['success']
    if not isinstance(success, bool):
        raise Exception('invalid success')

    events = ([_decode_event(event) for event in msg['events']]
              if success else None)

    return common.RegisterResMsg(register_id=register_id,
                                 success=success,
                                 events=events)


def _encode_query_req_msg(msg):
    return {'msg_type': 'query_req',
            'query_id': msg.query_id,
            **_encode_query_params(msg.params)}


def _decode_query_req_msg(msg):
    query_id = msg['query_id']
    if not isinstance(query_id, int):
        raise Exception('invalid query id')

    params = _decode_query_params(msg)

    return common.QueryReqMsg(query_id=query_id,
                              params=params)


def _encode_query_res_msg(msg):
    return {'msg_type': 'query_res',
            'query_id': msg.query_id,
            **_encode_query_result(msg.result)}


def _decode_query_res_msg(msg):
    query_id = msg['query_id']
    if not isinstance(query_id, int):
        raise Exception('invalid query id')

    result = _decode_query_result(msg)

    return common.QueryResMsg(query_id=query_id,
                              result=result)


def _encode_ping_req_msg(msg):
    return {'msg_type': 'ping_req',
            'ping_id': msg.ping_id}


def _decode_ping_req_msg(msg):
    ping_id = msg['ping_id']
    if not isinstance(ping_id, int):
        raise Exception('invalid ping id')

    return common.PingReqMsg(ping_id=ping_id)


def _encode_ping_res_msg(msg):
    return {'msg_type': 'ping_res',
            'ping_id': msg.ping_id}


def _decode_ping_res_msg(msg):
    ping_id = msg['ping_id']
    if not isinstance(ping_id, int):
        raise Exception('invalid ping id')

    return common.PingResMsg(ping_id=ping_id)


def _encode_event(event):
    event_id = _encode_event_id(event.id)
    event_type = _encode_event_type(event.type)
    timestamp = _encode_timestamp(event.timestamp)
    source_timestamp = (_encode_timestamp(event.source_timestamp)
                        if event.source_timestamp else None)
    payload = (_encode_event_payload(event.payload)
               if event.payload else None)

    return {'id': event_id,
            'type': event_type,
            'timestamp': timestamp,
            'source_timestamp': source_timestamp,
            'payload': payload}


def _decode_event(event):
    event_id = _decode_event_id(event['id'])
    event_type = _decode_event_type(event['type'])
    timestamp = _decode_timestamp(event['timestamp'])
    source_timestamp = (_decode_timestamp(event['source_timestamp'])
                        if event['source_timestamp'] is not None else None)
    payload = (_decode_event_payload(event['payload'])
               if event['payload'] is not None else None)

    return hat.event.common.Event(id=event_id,
                                  type=event_type,
                                  timestamp=timestamp,
                                  source_timestamp=source_timestamp,
                                  payload=payload)


def _encode_register_event(register_event):
    event_type = _encode_event_type(register_event.type)
    source_timestamp = (_encode_timestamp(register_event.source_timestamp)
                        if register_event.source_timestamp else None)
    payload = (_encode_event_payload(register_event.payload)
               if register_event.payload else None)

    return {'type': event_type,
            'source_timestamp': source_timestamp,
            'payload': payload}


def _decode_register_event(register_event):
    event_type = _decode_event_type(register_event['type'])
    source_timestamp = (_decode_timestamp(register_event['source_timestamp'])
                        if register_event['source_timestamp'] is not None
                        else None)
    payload = (_decode_event_payload(register_event['payload'])
               if register_event['payload'] is not None else None)

    return hat.event.common.RegisterEvent(type=event_type,
                                          source_timestamp=source_timestamp,
                                          payload=payload)


def _encode_query_params(params):
    if isinstance(params, hat.event.common.QueryLatestParams):
        return _encode_query_latest_params(params)

    if isinstance(params, hat.event.common.QueryTimeseriesParams):
        return _encode_query_timeseries_params(params)

    if isinstance(params, hat.event.common.QueryServerParams):
        return _encode_query_server_params(params)

    raise ValueError('unsupported query params')


def _decode_query_params(params):
    if params['query_type'] == 'latest':
        return _decode_query_latest_params(params)

    if params['query_type'] == 'timeseries':
        return _decode_query_timeseries_params(params)

    if params['query_type'] == 'server':
        return _decode_query_server_params(params)

    raise Exception('invalid query type')


def _encode_query_latest_params(params):
    params_json = {'query_type': 'latest'}

    if params.event_types is not None:
        params_json['event_types'] = [_encode_event_type(event_type)
                                      for event_type in params.event_types]

    return params_json


def _decode_query_latest_params(params):
    event_types = ([_decode_event_type(i) for i in params['event_types']]
                   if 'event_types' in params else None)

    return hat.event.common.QueryLatestParams(event_types=event_types)


def _encode_query_timeseries_params(params):
    params_json = {'query_type': 'timeseries',
                   'order': params.order.name,
                   'order_by': params.order_by.name}

    if params.event_types is not None:
        params_json['event_types'] = [_encode_event_type(event_type)
                                      for event_type in params.event_types]

    if params.t_from is not None:
        params_json['t_from'] = _encode_timestamp(params.t_from)

    if params.t_to is not None:
        params_json['t_to'] = _encode_timestamp(params.t_to)

    if params.source_t_from is not None:
        params_json['source_t_from'] = _encode_timestamp(params.source_t_from)

    if params.source_t_to is not None:
        params_json['source_t_to'] = _encode_timestamp(params.source_t_to)

    if params.max_results is not None:
        params_json['max_results'] = params.max_results

    if params.last_event_id is not None:
        params_json['last_event_id'] = _encode_event_id(params.last_event_id)

    return params_json


def _decode_query_timeseries_params(params):
    event_types = ([_decode_event_type(i) for i in params['event_types']]
                   if 'event_types' in params else None)
    t_from = (_decode_timestamp(params['t_from'])
              if 't_from' in params else None)
    t_to = (_decode_timestamp(params['t_to'])
            if 't_to' in params else None)
    source_t_from = (_decode_timestamp(params['source_t_from'])
                     if 'source_t_from' in params else None)
    source_t_to = (_decode_timestamp(params['source_t_to'])
                   if 'source_t_to' in params else None)
    order = hat.event.common.Order[params['order']]
    order_by = hat.event.common.OrderBy[params['order_by']]
    last_event_id = (_decode_event_id(params['last_event_id'])
                     if 'last_event_id' in params else None)

    max_results = params['max_results'] if 'max_results' in params else None
    if max_results is not None and not isinstance(max_results, int):
        raise Exception('invalid max results')

    return hat.event.common.QueryTimeseriesParams(event_types=event_types,
                                                  t_from=t_from,
                                                  t_to=t_to,
                                                  source_t_from=source_t_from,
                                                  source_t_to=source_t_to,
                                                  order=order,
                                                  order_by=order_by,
                                                  max_results=max_results,
                                                  last_event_id=last_event_id)


def _encode_query_server_params(params):
    params_json = {'query_type': 'server',
                   'server_id': params.server_id,
                   'persisted': params.persisted}

    if params.max_results is not None:
        params_json['max_results'] = params.max_results

    if params.last_event_id is not None:
        params_json['last_event_id'] = _encode_event_id(params.last_event_id)

    return params_json


def _decode_query_server_params(params):
    server_id = params['server_id']
    if not isinstance(server_id, int):
        raise Exception('invalid server id')

    persisted = params['persisted']
    if not isinstance(persisted, bool):
        raise Exception('invalid persisted')

    max_results = params['max_results'] if 'max_results' in params else None
    if max_results is not None and not isinstance(max_results, int):
        raise Exception('invalid max results')

    last_event_id = (_decode_event_id(params['last_event_id'])
                     if 'last_event_id' in params else None)

    return hat.event.common.QueryServerParams(server_id=server_id,
                                              persisted=persisted,
                                              max_results=max_results,
                                              last_event_id=last_event_id)


def _encode_query_result(result):
    return {'events': [_encode_event(event) for event in result.events],
            'more_follows': result.more_follows}


def _decode_query_result(result):
    events = [_decode_event(event) for event in result['events']]

    more_follows = result['more_follows']
    if not isinstance(more_follows, bool):
        raise Exception('invalid more follows')

    return hat.event.common.QueryResult(events=events,
                                        more_follows=more_follows)


def _encode_event_id(event_id):
    return {'server': event_id.server,
            'session': event_id.session,
            'instance': event_id.instance}


def _decode_event_id(event_id):
    server_id = event_id['server']
    if not isinstance(server_id, int):
        raise Exception('invalid server id')

    session_id = event_id['session']
    if not isinstance(session_id, int):
        raise Exception('invalid session id')

    instance_id = event_id['instance']
    if not isinstance(instance_id, int):
        raise Exception('invalid instance id')

    return hat.event.common.EventId(server=server_id,
                                    session=session_id,
                                    instance=instance_id)


def _encode_event_type(event_type):
    return list(event_type)


def _decode_event_type(event_type):
    if not isinstance(event_type, list):
        raise Exception('invalid event type')

    for i in event_type:
        if not isinstance(i, str):
            raise Exception('invalid event type')

    return tuple(event_type)


def _encode_timestamp(timestamp):
    return {'s': timestamp.s,
            'us': timestamp.us}


def _decode_timestamp(timestamp):
    s = timestamp['s']
    if not (isinstance(s, int)):
        raise Exception('invalid seconds')

    us = timestamp['us']
    if not (isinstance(us, int) and 0 <= us < 1_000_000):
        raise Exception('invalid microseconds')

    return hat.event.common.Timestamp(s=s,
                                      us=us)


def _encode_event_payload(payload):
    if isinstance(payload, hat.event.common.EventPayloadBinary):
        data = str(base64.b64encode(payload.data), encoding='utf-8')

        return {'payload_type': 'binary',
                'data_type': payload.type,
                'data': data}

    if isinstance(payload, hat.event.common.EventPayloadJson):
        return {'payload_type': 'json',
                'data': payload.data}

    raise ValueError('unsupported payload type')


def _decode_event_payload(payload):
    if payload['payload_type'] == 'binary':
        data_type = payload['data_type']
        if not isinstance(data_type, str):
            raise Exception('invalid data type')

        data = base64.b64decode(payload['data'].encode())

        return hat.event.common.EventPayloadBinary(type=data_type,
                                                   data=data)

    if payload['payload_type'] == 'json':
        return hat.event.common.EventPayloadJson(data=payload['data'])

    raise Exception('invalid payload type')
