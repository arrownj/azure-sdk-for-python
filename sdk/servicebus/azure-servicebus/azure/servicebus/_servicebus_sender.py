# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import logging
import time
import uuid
from typing import Any, TYPE_CHECKING, Union, List

import uamqp
from uamqp import SendClient, types

from ._base_handler import BaseHandler
from ._common import mgmt_handlers
from ._common.message import Message, BatchMessage
from .exceptions import (
    MessageSendFailed,
    OperationTimeoutError,
    _ServiceBusErrorPolicy
)
from ._common.utils import create_authentication
from ._common.constants import (
    REQUEST_RESPONSE_CANCEL_SCHEDULED_MESSAGE_OPERATION,
    REQUEST_RESPONSE_SCHEDULE_MESSAGE_OPERATION,
    MGMT_REQUEST_SEQUENCE_NUMBERS,
    MGMT_REQUEST_SESSION_ID,
    MGMT_REQUEST_MESSAGE,
    MGMT_REQUEST_MESSAGES,
    MGMT_REQUEST_MESSAGE_ID,
    MGMT_REQUEST_PARTITION_KEY,
    MGMT_REQUEST_VIA_PARTITION_KEY
)

if TYPE_CHECKING:
    import datetime
    from azure.core.credentials import TokenCredential

_LOGGER = logging.getLogger(__name__)


class SenderMixin(object):
    def _create_attribute(self):
        self._auth_uri = "sb://{}/{}".format(self.fully_qualified_namespace, self._entity_name)
        self._entity_uri = "amqps://{}/{}".format(self.fully_qualified_namespace, self._entity_name)
        self._error_policy = _ServiceBusErrorPolicy(max_retries=self._config.retry_total)
        self._name = "SBSender-{}".format(uuid.uuid4())
        self._max_message_size_on_link = 0
        self.entity_name = self._entity_name

    def _set_msg_timeout(self, timeout=None, last_exception=None):
        if not timeout:
            return
        timeout_time = time.time() + timeout
        remaining_time = timeout_time - time.time()
        if remaining_time <= 0.0:
            if last_exception:
                error = last_exception
            else:
                error = OperationTimeoutError("Send operation timed out")
            _LOGGER.info("%r send operation timed out. (%r)", self._name, error)
            raise error
        self._handler._msg_timeout = remaining_time * 1000  # type: ignore  # pylint: disable=protected-access

    @classmethod
    def _build_schedule_request(cls, schedule_time_utc, *messages):
        request_body = {MGMT_REQUEST_MESSAGES: []}
        for message in messages:
            message.schedule(schedule_time_utc)
            message_data = {}
            message_data[MGMT_REQUEST_MESSAGE_ID] = message.properties.message_id
            if message.properties.group_id:
                message_data[MGMT_REQUEST_SESSION_ID] = message.properties.group_id
            if message.partition_key:
                message_data[MGMT_REQUEST_PARTITION_KEY] = message.partition_key
            if message.via_partition_key:
                message_data[MGMT_REQUEST_VIA_PARTITION_KEY] = message.via_partition_key
            message_data[MGMT_REQUEST_MESSAGE] = bytearray(message.message.encode_message())
            request_body[MGMT_REQUEST_MESSAGES].append(message_data)
        return request_body


class ServiceBusSender(BaseHandler, SenderMixin):
    """The ServiceBusSender class defines a high level interface for
    sending messages to the Azure Service Bus Queue or Topic.

    :ivar fully_qualified_namespace: The fully qualified host name for the Service Bus namespace.
     The namespace format is: `<yournamespace>.servicebus.windows.net`.
    :vartype fully_qualified_namespace: str
    :ivar entity_name: The name of the entity that the client connects to.
    :vartype entity_name: str

    :param str fully_qualified_namespace: The fully qualified host name for the Service Bus namespace.
     The namespace format is: `<yournamespace>.servicebus.windows.net`.
    :param ~azure.core.credentials.TokenCredential credential: The credential object used for authentication which
     implements a particular interface for getting tokens. It accepts
     :class:`ServiceBusSharedKeyCredential<azure.servicebus.ServiceBusSharedKeyCredential>`, or credential objects
     generated by the azure-identity library and objects that implement the `get_token(self, *scopes)` method.
    :keyword str queue_name: The path of specific Service Bus Queue the client connects to.
    :keyword str topic_name: The path of specific Service Bus Topic the client connects to.
    :keyword bool logging_enable: Whether to output network trace logs to the logger. Default is `False`.
    :keyword int retry_total: The total number of attempts to redo a failed operation when an error occurs.
     Default value is 3.
    :keyword transport_type: The type of transport protocol that will be used for communicating with
     the Service Bus service. Default is `TransportType.Amqp`.
    :paramtype transport_type: ~azure.servicebus.TransportType
    :keyword dict http_proxy: HTTP proxy settings. This must be a dictionary with the following
     keys: `'proxy_hostname'` (str value) and `'proxy_port'` (int value).
     Additionally the following keys may also be present: `'username', 'password'`.

    .. admonition:: Example:

        .. literalinclude:: ../samples/sync_samples/sample_code_servicebus.py
            :start-after: [START create_servicebus_sender_sync]
            :end-before: [END create_servicebus_sender_sync]
            :language: python
            :dedent: 4
            :caption: Create a new instance of the ServiceBusSender.

    """
    def __init__(
        self,
        fully_qualified_namespace,
        credential,
        **kwargs
    ):
        # type: (str, TokenCredential, Any) -> None
        if kwargs.get("entity_name"):
            super(ServiceBusSender, self).__init__(
                fully_qualified_namespace=fully_qualified_namespace,
                credential=credential,
                **kwargs
            )
        else:
            queue_name = kwargs.get("queue_name")
            topic_name = kwargs.get("topic_name")
            if queue_name and topic_name:
                raise ValueError("Queue/Topic name can not be specified simultaneously.")
            if not (queue_name or topic_name):
                raise ValueError("Queue/Topic name is missing. Please specify queue_name/topic_name.")
            entity_name = queue_name or topic_name
            super(ServiceBusSender, self).__init__(
                fully_qualified_namespace=fully_qualified_namespace,
                credential=credential,
                entity_name=entity_name,
                **kwargs
            )

        self._max_message_size_on_link = 0
        self._create_attribute()
        self._connection = kwargs.get("connection")

    def _create_handler(self, auth):
        self._handler = SendClient(
            self._entity_uri,
            auth=auth,
            debug=self._config.logging_enable,
            properties=self._properties,
            error_policy=self._error_policy,
            client_name=self._name,
            encoding=self._config.encoding
        )

    def _open(self):
        # pylint: disable=protected-access
        if self._running:
            return
        if self._handler:
            self._handler.close()

        auth = None if self._connection else create_authentication(self)
        self._create_handler(auth)
        try:
            self._handler.open(connection=self._connection)
            while not self._handler.client_ready():
                time.sleep(0.05)
            self._running = True
            self._max_message_size_on_link = self._handler.message_handler._link.peer_max_message_size \
                                             or uamqp.constants.MAX_MESSAGE_LENGTH_BYTES
        except:
            self.close()
            raise

    def _send(self, message, timeout=None, last_exception=None):
        self._open()
        self._set_msg_timeout(timeout, last_exception)
        try:
            self._handler.send_message(message.message)
        except Exception as e:
            raise MessageSendFailed(e)

    def _schedule(self, message, schedule_time_utc):
        # type: (Union[Message, BatchMessage], datetime.datetime) -> List[int]
        """Send Message or BatchMessage to be enqueued at a specific time.
        Returns a list of the sequence numbers of the enqueued messages.
        :param message: The messages to schedule.
        :type message: ~azure.servicebus.Message or ~azure.servicebus.BatchMessage
        :param schedule_time_utc: The utc date and time to enqueue the messages.
        :type schedule_time_utc: ~datetime.datetime
        :rtype: List[int]

        .. admonition:: Example:

            .. literalinclude:: ../samples/sync_samples/sample_code_servicebus.py
                :start-after: [START scheduling_messages]
                :end-before: [END scheduling_messages]
                :language: python
                :dedent: 4
                :caption: Schedule a message to be sent in future
        """
        # pylint: disable=protected-access
        self._open()
        if isinstance(message, BatchMessage):
            request_body = self._build_schedule_request(schedule_time_utc, *message._messages)
        else:
            request_body = self._build_schedule_request(schedule_time_utc, message)
        return self._mgmt_request_response_with_retry(
            REQUEST_RESPONSE_SCHEDULE_MESSAGE_OPERATION,
            request_body,
            mgmt_handlers.schedule_op
        )

    def _cancel_scheduled_messages(self, sequence_numbers):
        # type: (Union[int, List[int]]) -> None
        """
        Cancel one or more messages that have previously been scheduled and are still pending.

        :param sequence_numbers: The sequence numbers of the scheduled messages.
        :type sequence_numbers: int or list[int]
        :rtype: None

        .. admonition:: Example:

            .. literalinclude:: ../samples/sync_samples/sample_code_servicebus.py
                :start-after: [START cancel_scheduled_messages]
                :end-before: [END cancel_scheduled_messages]
                :language: python
                :dedent: 4
                :caption: Cancelling messages scheduled to be sent in future
        """
        self._open()
        if isinstance(sequence_numbers, int):
            numbers = [types.AMQPLong(sequence_numbers)]
        else:
            numbers = [types.AMQPLong(s) for s in sequence_numbers]
        request_body = {MGMT_REQUEST_SEQUENCE_NUMBERS: types.AMQPArray(numbers)}
        return self._mgmt_request_response_with_retry(
            REQUEST_RESPONSE_CANCEL_SCHEDULED_MESSAGE_OPERATION,
            request_body,
            mgmt_handlers.default
        )

    @classmethod
    def from_connection_string(
        cls,
        conn_str,
        **kwargs
    ):
        # type: (str, Any) -> ServiceBusSender
        """Create a ServiceBusSender from a connection string.

        :param conn_str: The connection string of a Service Bus.
        :keyword str queue_name: The path of specific Service Bus Queue the client connects to.
         Only one of queue_name or topic_name can be provided.
        :keyword str topic_name: The path of specific Service Bus Topic the client connects to.
         Only one of queue_name or topic_name can be provided.
        :keyword bool logging_enable: Whether to output network trace logs to the logger. Default is `False`.
        :keyword int retry_total: The total number of attempts to redo a failed operation when an error occurs.
         Default value is 3.
        :keyword transport_type: The type of transport protocol that will be used for communicating with
         the Service Bus service. Default is `TransportType.Amqp`.
        :paramtype transport_type: ~azure.servicebus.TransportType
        :keyword dict http_proxy: HTTP proxy settings. This must be a dictionary with the following
         keys: `'proxy_hostname'` (str value) and `'proxy_port'` (int value).
         Additionally the following keys may also be present: `'username', 'password'`.
        :rtype: ~azure.servicebus.ServiceBusSenderClient

        .. admonition:: Example:

            .. literalinclude:: ../samples/sync_samples/sample_code_servicebus.py
                :start-after: [START create_servicebus_sender_from_conn_str_sync]
                :end-before: [END create_servicebus_sender_from_conn_str_sync]
                :language: python
                :dedent: 4
                :caption: Create a new instance of the ServiceBusSender from connection string.

        """
        constructor_args = cls._from_connection_string(
            conn_str,
            **kwargs
        )
        return cls(**constructor_args)

    def send(self, message):
        # type: (Union[Message, BatchMessage], float) -> None
        """Sends message and blocks until acknowledgement is received or operation times out.

        :param message: The ServiceBus message to be sent.
        :type message: ~azure.servicebus.Message
        :rtype: None
        :raises: ~azure.servicebus.common.errors.MessageSendFailed if the message fails to
         send or ~azure.servicebus.common.errors.OperationTimeoutError if sending times out.

        .. admonition:: Example:

            .. literalinclude:: ../samples/sync_samples/sample_code_servicebus.py
                :start-after: [START send_sync]
                :end-before: [END send_sync]
                :language: python
                :dedent: 4
                :caption: Send message.

        """
        self._do_retryable_operation(
            self._send,
            message=message,
            require_timeout=True,
            require_last_exception=True
        )

    def create_batch(self, max_size_in_bytes=None):
        # type: (int) -> BatchMessage
        """Create a BatchMessage object with the max size of all content being constrained by max_size_in_bytes.
        The max_size should be no greater than the max allowed message size defined by the service.

        :param int max_size_in_bytes: The maximum size of bytes data that a BatchMessage object can hold. By
         default, the value is determined by your Service Bus tier.
        :rtype: ~azure.servicebus.BatchMessage

        .. admonition:: Example:

            .. literalinclude:: ../samples/sync_samples/sample_code_servicebus.py
                :start-after: [START create_batch_sync]
                :end-before: [END create_batch_sync]
                :language: python
                :dedent: 4
                :caption: Create BatchMessage object within limited size

        """
        if not self._max_message_size_on_link:
            self._open_with_retry()

        if max_size_in_bytes and max_size_in_bytes > self._max_message_size_on_link:
            raise ValueError(
                "Max message size: {} is too large, acceptable max batch size is: {} bytes.".format(
                    max_size_in_bytes, self._max_message_size_on_link
                )
            )

        return BatchMessage(
            max_size_in_bytes=(max_size_in_bytes or self._max_message_size_on_link)
        )
