.. _mariner:

Mariner
=======

Mariner communication protocol enables communication between Mariner Server
and Mariner Client, based on TCP communication with JSON encoded messages.
It is desined as communication interface between Hat-based systems and
external applications. Exchange of data is based on sending/receiving
event structures.

For more information on event structures, see
`<https://hat-event.hat-open.com/event.html>`_.


Transport
---------

Mariner Server and Mariner Client (in the remainder of this document, mostly
referred only as `server` and `client`) communicate by establishing
TCP connection. Server opens listening socket and accepts new TCP connections
initiated by client. In addition to non encrypted communication, TCP stream
can be wrapped in SSL layer. Both server and client can close TCP connection
at any time, thus closing Mariner communication.

For each connection, underlying TCP stream is segmented into blocks. Each block
contains a single communication message prefixed by its message header. This
header consists of `1+m` bytes where the first byte contains the value `m`
(header byte length), while following `m` bytes contain value `k` (message byte
length) encoded as big-endian (the first byte value does not include the first
header byte and message length does not include header length). Message itself
is utf-8 encoded JSON value.

Visualization of the communication stream::

    address    ...  |  n  | n+1 |  ...  | n+m | n+m+1 |  ...  | n+m+k |  ...
             -------+-----+-----+-------+-----+-------+-------+-------+-------
       data    ...  |  m  |         k         |        message        |  ...
             -------+-----+-----+-------+-----+-------+-------+-------+-------

where:

* `m` is byte length of `k` (header length without first byte)
* `k` is byte length of `message` (`n+1` is the most significant byte)
* `message` is JSON encoded message


Messages
--------

Communication between server and client is based on full-duplex message
passing where both server and client can send/receive messages at any time.
Single message is represented with JSON Object with mandatory property
``msg_type`` (value of this property is always string). Property with key
``msg_type`` represents type of communication message. Existence and semantics
of other properties is dependent of message type. Structure of messages is
defined by JSON Schema ``hat-mariner://mariner.yaml#`` (see
`JSON Schema definitions`_).

Supported messages (identified by message type) are:

* `init_req`

   Initial message sent by client. This message can be sent only once,
   immediately after establishment of TCP connection. This message
   identifies client and contains additional initialization parameters.

   Properties:

   * `client_name`

     Label used as client identification.

   * `client_token`

     Optional client token. Additional client identification which can be used
     for authentication or state synchronization between client and server.

   * `subscriptions`

     List of event types (including query subtypes) which is used as filter
     for future event notifications. Only events with types satisfying
     subscriptions will be notified to client.

   * `server_id`

     Optional identification of server used for filtering of notified events.
     Only events originating from specified server will be notified to client.
     If server id is not specified, all events (that satisfy subscription) are
     notified to client.

   * persisted

     Flag indicating when should server send event notifications to client.
     If this property is ``true``, server should send notifications after
     events are persisted. If this property is ``false``, server should send
     notifications immediately after event registration.

* `init_res`

  Initial message sent by server. This message is sent after receiving
  `init_req` message and informs client of connection establishment success.

  Properties:

  * `success`

    Connection establishment success.

  * `status`

    Parameter available in case of success ``true``. Represents current server
    status.

  * `error`

    Parameter available in case of success ``false``. Represents additional
    human readable error message.

* `status`

  Message sent by server on each server's status change.

  Properties:

  * `status`

    Server status (`STANDBY` or `OPERATIONAL`).

* `events`

  Message sent by server. This message is used to notify client with newly
  created events.

  Properties:

  * `events`

    List of events.

* `register_req`

  Message sent by client. This message enables client to submit new registration
  request. Single message can contain multiple register events.

  Properties:

  * `register_id`

    Request identifier set by client. Server will include same identifier in
    associated response message.

  * `register_events`

    List of register events.

* `register_res`

  Message sent by server as response to `register_req`.

  Properties:

  * `register_id`

    Identifier matching one included in associated request message.

  * `success`

    Flag indicating registration success.

  * `events`

    List of associated events available only in case of success ``true``.

* `query_req`

  Query previously created events. Each query request contains `query_type`
  identifying query type.

  Query types:

  * `latest`

    Query latest events for each specified event type.

    Properties:

    * `query_id`

      Request identifier set by client. Server will include same identifier in
      associated response message.

    * `event_types`

      Optional list of event type queries. If not specified, ``*`` is assumed.

  * `timeseries`

    Query timeseries events.

    Properties:

    * `query_id`

      Request identifier set by client. Server will include same identifier in
      associated response message.

    * `event_types`

      Optional list of event type queries. If not specified, ``*`` is assumed.

    * `t_from`

      Optional timestamp used as timestamp filter. If specified, queried events
      must have timestamp greater or equal than `t_from`.

    * `t_to`

      Optional timestamp used as timestamp filter. If specified, queried events
      must have timestamp less or equal than `t_to`.

    * `source_t_from`

      Optional timestamp used as source timestamp filter. If specified, queried
      events must have source timestamp greater or equal than `t_from`.

    * `source_t_to`

      Optional timestamp used as source timestamp filter. If specified, queried
      events must have source timestamp less or equal than `t_to`.

    * `order`

      Indication selecting descending or ascending order.

    * `order_by`

      Indication selecting timestamp based or source timestamp based timeseries.

    * `max_results`

      Optional limit to maximum number of events included in query result. In
      addition to client provided `max_result`, server can apply additional
      limitations to number of events.

    * `last_event_id`

      Optional event identifier defining "starting event" for query result.
      This event is not included in query result.

  * `server`

    Query all events registered by specified server.

    Properties:

    * `query_id`

      Request identifier set by client. Server will include same identifier in
      associated response message.

    * `server_id`

      Server identifier used as filter for event in query result.

    * `persisted`

      Flag indicating queried event status. If this flag is ``true``, only
      persisted events are reported in query result.

    * `max_results`

      Optional limit to maximum number of events included in query result. In
      addition to client provided `max_result`, server can apply additional
      limitations to number of events.

    * `last_event_id`

      Optional event identifier defining "starting event" for query result.
      This event is not included in query result.

* `query_res`

  Query result.

  Properties:

  * `query_id`

    Identifier matching one included in associated request message.

  * `events`

    List of events.

  * `more_follows`

    Flag indicating if more events satisfying query are available. This
    events can be obtained by repeating sending previous query request with
    addition of `last_event_id` set to last reported event identifier.

* `ping_req`

  Can be sent by both server and client. Once server or client received this
  message, it should immediately send `ping_res` message.

  Properties:

  * `ping_id`

    Request identifier set by client. Server will include same identifier in
    associated response message.

* `ping_res`

  Can be sent by both server and client. Represents response to `ping_req`
  message`.

  Properties:

  * `ping_id`

    Identifier matching one included in associated request message.


Communication
-------------

Mariner communication closely mimics communication specified by Eventer
communication protocol. For more information, see
`<https://hat-event.hat-open.com/eventer.html>`_.

Notable differences to Eventer communications are:

* Status acknowledgment message is not available.

* Request/response messages (except for `init_req`/`init_res`) include
  request identifier. This arbitrary number is set by client in request message
  and repeated in associated response message sent by server.

* `ping_req`/`ping_res` messages are available.


JSON Schema definitions
-----------------------

.. literalinclude:: ../schemas_json/mariner.yaml
    :language: yaml
